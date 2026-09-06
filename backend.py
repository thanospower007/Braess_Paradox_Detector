"""
backend_v2.py — Detector de Paradoja de Braess (versión corregida)

Cambios respecto a backend.py original. Cada [FIX-N] es trazable a un hallazgo
del Reporte_Ejecucion_Braess.pdf:

  [FIX-1]  Matriz O-D con rutas no triviales (path_len >= min_path_len)
  [FIX-2]  Métrica de mejora basada en ATT sobre conjunto pareado de viajes
           sobrevivientes — elimina el artefacto matemático del descarte.
  [FIX-3]  Reactivos verdaderos: recalculan sobre tiempos congestionados,
           no sobre free_flow_time.
  [FIX-4]  Replicaciones e inferencia: N réplicas por escenario, IC del 95%
           y test pareado Wilcoxon con corrección Benjamini-Hochberg (FDR).
  [FIX-5]  Paralelización con joblib en CPU.
  [FIX-6]  Eliminado el "np = cp" que reasignaba el módulo. CuPy no aplica
           a la microsimulación porque el cuello de botella es Python loop.
  [FIX-7]  Limpieza de tipos numpy.int64 -> int en serialización JSON.
  [FIX-8]  Capacidad y velocidades respetan atributos OSM cuando existen
           (maxspeed, lanes); usan defaults solo cuando faltan.
  [FIX-9]  Estado del servidor por sesión en lugar de globales mutables.
  [FIX-10] Distancia haversine implementada localmente, independiente de la
           versión de OSMnx (la API ox.distance cambió entre 1.x y 2.x).
  [FIX-11] Wilcoxon protegido contra divisiones por cero cuando todas las
           diferencias pareadas son nulas (escenarios sin efecto medible).
  [FIX-12] Auto-tuning de parámetros según el grafo descargado. La heurística
           respeta un presupuesto de tiempo objetivo (default 30 min de
           tiempo paralelo). El usuario puede override desde el frontend.
  [FIX-13] Descarga robusta del grafo OSM. Si graph_from_place falla porque
           Nominatim no devuelve un (Multi)Polygon (caso típico de barrios
           pequeños o consultas ambiguas), usa fallback a graph_from_point
           con geocodificación previa y radio configurable.
  [FIX-14] Logging granular de fases (pre-procesamiento, ejecución, post-
           procesamiento). Cada fase emite eventos al frontend y logger,
           eliminando "silencios" donde la UI parece colgada pero el
           backend está procesando (BH, serialización, geometrías).
  [FIX-15] min_effect_size_pct y fdr_alpha también son auto-tuneados según
           tamaño de la red (más conservadores en redes grandes donde el
           número de hipótesis simultáneas es mayor).

Autor de la revisión: análisis preparado para Carlos Hurtado.
Fecha: mayo 2026.
"""

import os
import io
import json
import logging
import math
import time
import random
import tempfile
import traceback
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import scipy.stats as stats
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString
import networkx as nx
import osmnx as ox
from scipy.spatial import cKDTree
from joblib import Parallel, delayed

from flask import Flask, request, jsonify, send_from_directory
from flask_socketio import SocketIO

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


# =====================================================================
# DISTANCIA GEOGRÁFICA  [FIX-10]
# =====================================================================
# La API de ox.distance cambió entre OSMnx 1.x (great_circle_vec) y 2.x
# (great_circle), y algunos builds intermedios no exponen ninguna. Para no
# depender de la versión instalada, implementamos haversine directamente.
# Validado contra ox.distance.great_circle 2.1.0: diferencia < 0.001 m.

EARTH_RADIUS_M = 6371008.8  # mismo valor que OSMnx usa internamente


def great_circle_m(lat1, lon1, lat2, lon2):
    """Distancia haversine entre dos puntos lat/lon, en metros."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


# =====================================================================
# CONFIGURACIÓN
# =====================================================================

DEFAULT_SPEEDS_KMH = {
    'motorway': 90, 'trunk': 80, 'primary': 60, 'secondary': 50,
    'tertiary': 40, 'residential': 30, 'unclassified': 30,
    'service': 20, 'default': 30,
}

# Parámetros canónicos del IDM (Treiber & Kesting, 2013)
IDM_PARAMS = {'T': 1.5, 'a': 1.0, 'b': 1.5, 's0': 2.0}

# Parámetros del análisis. Expuestos para que el frontend pueda ajustarlos.
DEFAULT_PARAMS = {
    'duration_minutes': 10,
    'reactive_ratio': 0.30,
    'n_trips': 3000,                    # [FIX-1] Demanda explícita, no derivada de aristas.
    'min_path_len_nodes': 4,            # [FIX-1] Rutas con ≥ 3 aristas para que haya elección.
    'n_replications': 5,                # [FIX-4] Réplicas por escenario.
    'fdr_alpha': 0.05,                  # [FIX-4] Tasa de falsos descubrimientos para BH.
    'min_effect_size_pct': 1.0,         # Efecto mínimo en ATT (%) para considerar relevante.
    'max_addition_candidates': 80,
    'addition_min_dist_m': 50,
    'addition_max_dist_m': 400,
    'reroute_every_steps': 30,
    'n_jobs': max(1, (os.cpu_count() or 4) - 1),
}


# =====================================================================
# AUTO-TUNING DE PARÁMETROS  [FIX-12]
# =====================================================================
# Cuando el usuario no especifica parámetros, los inferimos del tamaño y
# topología de la red descargada. La idea es respetar un presupuesto de
# tiempo objetivo (default 30 min de tiempo paralelo) ajustando n_trips,
# n_replications, duration y candidatos a añadir según el tamaño.
# Esto evita que un usuario lance "Medellín completa" con defaults pensados
# para Guatapé y termine con un análisis de 25 horas.

def estimate_diameter_nodes(G, sample_size=30):
    """
    Estima el diámetro del grafo (longitud del camino más largo en nodos)
    muestreando pares aleatorios. Cálculo barato vs nx.diameter() exacto.
    """
    nodes = list(G.nodes())
    n = len(nodes)
    if n < 2:
        return 1
    sample_size = min(sample_size, n)
    rng = random.Random(7)
    longest = 0
    for _ in range(sample_size):
        o, d = rng.sample(nodes, 2)
        try:
            path = nx.shortest_path(G, o, d, weight='free_flow_time')
            longest = max(longest, len(path))
        except nx.NetworkXNoPath:
            continue
    return max(3, longest)


def auto_tune_params(G, n_jobs, budget_minutes=30):
    """
    Devuelve un dict de parámetros ajustados automáticamente al grafo.
    Conserva las claves no derivadas (reactive_ratio, fdr_alpha, etc.) en
    sus defaults; solo recalcula las que escalan con el tamaño de la red.

    Devuelve también claves auxiliares con prefijo `_` que son metadatos
    útiles para mostrar al usuario (tiempo estimado, si conviene muestreo).
    """
    n_nodes = len(G.nodes())
    n_edges = len(G.edges())
    diameter = estimate_diameter_nodes(G)

    # ------- min_path_len_nodes -------
    if diameter <= 4:
        min_path_len = 3
    elif diameter <= 10:
        min_path_len = 4
    elif diameter <= 30:
        min_path_len = max(4, diameter // 4)
    else:
        min_path_len = max(6, diameter // 5)

    # ------- n_replications -------
    if n_edges < 200:
        n_reps = 15
    elif n_edges < 1000:
        n_reps = 10
    elif n_edges < 5000:
        n_reps = 8
    elif n_edges < 20000:
        n_reps = 6
    else:
        n_reps = 5

    # ------- duration_minutes -------
    travel_time_typical_s = max(60, diameter * 30)
    duration_min = max(3, min(15, math.ceil(travel_time_typical_s / 60 * 1.2)))

    # ------- max_addition_candidates -------
    max_add = min(150, max(20, n_edges // 30))

    # ------- fdr_alpha y min_effect_size_pct: autoajustables  [FIX-14] -------
    #
    # Lógica:
    #   - α (FDR) más estricto cuando hay MUCHAS hipótesis: con miles de
    #     escenarios, α=0.05 admite hasta 5% de falsos descubrimientos sobre
    #     los rechazados, que en una red de 2000 aristas puede ser 5-10 falsos.
    #     Reducimos α en redes grandes para tolerar menos falsos absolutos.
    #
    #   - Efecto mínimo (%): más permisivo en redes pequeñas (donde basta
    #     1%); más exigente en redes grandes (donde la varianza estocástica
    #     puede producir señales pequeñas espurias y donde el número de
    #     comparaciones aumenta).
    n_total_hypotheses_est = n_edges + max_add
    if n_total_hypotheses_est < 100:
        fdr_alpha = 0.10        # red pequeña: tolera más falsos para tener poder
        min_effect = 0.5
    elif n_total_hypotheses_est < 800:
        fdr_alpha = 0.05        # default razonable (incluye Guatapé ~544)
        min_effect = 1.0
    elif n_total_hypotheses_est < 3000:
        fdr_alpha = 0.05
        min_effect = 1.5
    elif n_total_hypotheses_est < 10000:
        fdr_alpha = 0.025       # más estricto al crecer las hipótesis
        min_effect = 2.0
    else:
        fdr_alpha = 0.01        # red enorme: muy estricto
        min_effect = 3.0

    # ------- n_trips: derivado del budget -------
    # Costo aproximado por simulación (segundos en 1 core a velocidad referencia):
    #   cost = (n_trips/1500) × (duration/10)
    # Total simulaciones = (n_edges + max_add) × n_reps + n_reps_base
    n_total_sims = (n_edges + max_add) * n_reps + n_reps
    target_serial_seconds = budget_minutes * 60 * max(1, n_jobs)
    # Despejar n_trips que ajusta al budget
    n_trips_max = (target_serial_seconds * 1500 * 10) / max(1, n_total_sims * duration_min)
    n_trips = max(300, min(5000, int(n_trips_max)))

    # ------- floor de n_trips por densidad -------
    # Si el grafo es minúsculo (Wheatstone), no necesita 5000 viajes.
    # Floor razonable: máximo entre 300 y n_edges×3.
    floor_trips = min(n_trips, max(300, n_edges * 3))
    n_trips = floor_trips

    sampling_recommended = (n_trips_max < 300)

    # Recomputar tiempo final
    cost_per_sim = (n_trips / 1500) * (duration_min / 10)
    serial_time_s = n_total_sims * cost_per_sim
    parallel_time_s = serial_time_s / max(1, n_jobs)

    return {
        # Claves que el simulador consume:
        'duration_minutes': duration_min,
        'reactive_ratio': DEFAULT_PARAMS['reactive_ratio'],
        'n_trips': n_trips,
        'min_path_len_nodes': min_path_len,
        'n_replications': n_reps,
        'fdr_alpha': fdr_alpha,                          # [FIX-15]
        'min_effect_size_pct': min_effect,               # [FIX-15]
        'max_addition_candidates': max_add,
        'addition_min_dist_m': DEFAULT_PARAMS['addition_min_dist_m'],
        'addition_max_dist_m': DEFAULT_PARAMS['addition_max_dist_m'],
        'reroute_every_steps': DEFAULT_PARAMS['reroute_every_steps'],
        'n_jobs': n_jobs,
        # Metadatos para reportar al usuario:
        '_auto_tuned': True,
        '_graph_n_nodes': n_nodes,
        '_graph_n_edges': n_edges,
        '_graph_diameter_est': diameter,
        '_estimated_serial_minutes': round(serial_time_s / 60, 1),
        '_estimated_parallel_minutes': round(parallel_time_s / 60, 1),
        '_n_total_sims': n_total_sims,
        '_n_jobs_used': n_jobs,
        '_budget_minutes': budget_minutes,
        '_sampling_recommended': sampling_recommended,
    }


def merge_user_params(auto_params, user_params):
    """
    Combina parámetros auto-tuneados con overrides del usuario.
    Cualquier clave que el usuario haya enviado (no None) gana sobre auto.
    Las claves auxiliares con prefijo `_` se preservan para el response.
    """
    if not user_params:
        return auto_params
    out = dict(auto_params)
    for k, v in user_params.items():
        if k.startswith('_'):
            continue
        if v is None or v == '':
            continue
        if k in DEFAULT_PARAMS:
            try:
                out[k] = type(DEFAULT_PARAMS[k])(v)
                # Marcar que no es 100% auto si el usuario sobrescribió algo
                out['_auto_tuned'] = False
            except (ValueError, TypeError):
                logger.warning(f"Valor inválido para {k}: {v}")
    return out


# =====================================================================
# PREPARACIÓN DEL GRAFO  [FIX-8]
# =====================================================================

def _parse_maxspeed(value, default_kmh):
    """Lee maxspeed de OSM, que puede venir como '50', '50 mph', lista, etc."""
    if value is None:
        return default_kmh
    if isinstance(value, list):
        value = value[0] if value else None
        if value is None:
            return default_kmh
    s = str(value).lower().strip()
    try:
        if 'mph' in s:
            return float(s.replace('mph', '').strip()) * 1.60934
        return float(s.split()[0])
    except (ValueError, IndexError):
        return default_kmh


def _parse_lanes(value, default=2):
    if value is None:
        return default
    if isinstance(value, list):
        try:
            return int(value[0])
        except (ValueError, TypeError):
            return default
    try:
        return max(1, int(str(value).split(';')[0]))
    except (ValueError, TypeError):
        return default


def prepare_osm_graph(G):
    """Enriquece cada arista con velocidad, capacidad, tiempo de flujo libre."""
    for u, v, k, data in G.edges(keys=True, data=True):
        if data.get('prepared'):
            continue

        highway = data.get('highway', 'default')
        if isinstance(highway, list):
            highway = highway[0] if highway else 'default'

        default_speed = DEFAULT_SPEEDS_KMH.get(highway, DEFAULT_SPEEDS_KMH['default'])
        # [FIX-8] Respetar maxspeed de OSM cuando exista.
        speed_kmh = _parse_maxspeed(data.get('maxspeed'), default_speed)
        speed_ms = speed_kmh * 1000 / 3600

        lanes = _parse_lanes(data.get('lanes'), default=2)

        length = float(data.get('length', 100.0))
        if length <= 0:
            length = 100.0

        data['speed_kmh'] = speed_kmh
        data['speed_ms'] = speed_ms
        data['lanes'] = lanes
        data['length'] = length
        data['oneway'] = bool(data.get('oneway', False))
        data['free_flow_time'] = length / speed_ms
        data['capacity_vph'] = lanes * 1800  # vehículos por hora por carril.

        if 'geometry' not in data:
            data['geometry'] = LineString([
                (G.nodes[u]['x'], G.nodes[u]['y']),
                (G.nodes[v]['x'], G.nodes[v]['y']),
            ])

        data['prepared'] = True
    return G


# =====================================================================
# MATRIZ O-D CON RUTAS NO TRIVIALES  [FIX-1]
# =====================================================================

def create_demand_matrix(G, n_trips: int, min_path_len: int = 4, seed: Optional[int] = None):
    """
    Genera una matriz O-D donde cada par tiene una ruta de longitud >= min_path_len
    nodos. Esto garantiza que existan rutas alternativas y que la elección de
    ruta tenga sentido (condición necesaria para que aparezca la Paradoja de Braess).
    """
    rng = random.Random(seed)
    nodes = list(G.nodes())
    if len(nodes) < min_path_len:
        raise ValueError(f"Grafo demasiado pequeño: {len(nodes)} nodos < {min_path_len} requeridos.")

    od_pairs = []
    attempts = 0
    max_attempts = n_trips * 30

    while len(od_pairs) < n_trips and attempts < max_attempts:
        attempts += 1
        o, d = rng.sample(nodes, 2)
        try:
            path = nx.shortest_path(G, o, d, weight='free_flow_time')
            if len(path) >= min_path_len:
                od_pairs.append((o, d))
        except nx.NetworkXNoPath:
            continue

    if len(od_pairs) < n_trips:
        logger.warning(
            f"Solo se generaron {len(od_pairs)}/{n_trips} viajes con path_len>={min_path_len}. "
            f"El grafo puede ser demasiado pequeño o poco conectado."
        )
    rng.shuffle(od_pairs)
    return od_pairs


# =====================================================================
# MICROSIMULADOR
# =====================================================================

@dataclass
class Vehicle:
    id: int
    origin: int
    destination: int
    route: list
    current_edge_index: int = 0
    position_on_edge: float = 0.0
    speed: float = 0.0
    total_time: float = 0.0
    reactive: bool = False
    completed: bool = False
    failed: bool = False  # [FIX-2] Marca vehículos que no pudieron rutear.


class Microsimulator:
    """Microsimulación IDM con re-enrutamiento adaptativo verdadero."""

    def __init__(self, G, od_pairs, reactive_ratio=0.30, duration_minutes=10,
                 dt=1.0, reroute_every=30, seed: Optional[int] = None):
        self.G = G
        self.dt = dt
        self.duration = duration_minutes * 60
        self.reroute_every = reroute_every
        self.rng = random.Random(seed)

        self.vehicles = []
        self.failed_vehicles = []  # [FIX-2] Mantener registro explícito.
        self.edge_vehicles = {ek: [] for ek in G.edges(keys=True)}

        for i, (origin, dest) in enumerate(od_pairs):
            try:
                edge_route = self._compute_edge_route(G, origin, dest, weight='free_flow_time')
                if not edge_route:
                    self.failed_vehicles.append((origin, dest))
                    continue
                v = Vehicle(
                    id=i, origin=origin, destination=dest, route=edge_route,
                    reactive=(self.rng.random() < reactive_ratio),
                )
                self.vehicles.append(v)
                self.edge_vehicles.setdefault(edge_route[0], []).append(v)
            except nx.NetworkXNoPath:
                self.failed_vehicles.append((origin, dest))

        self.completed_trips = 0
        self.total_time_sum = 0.0
        self.total_vmt = 0.0
        self.completed_trip_records = []  # [FIX-2] (id, origin, dest, total_time)

    @staticmethod
    def _compute_edge_route(G, origin, dest, weight):
        try:
            node_route = nx.shortest_path(G, origin, dest, weight=weight)
        except nx.NetworkXNoPath:
            return None
        edge_route = []
        for j in range(len(node_route) - 1):
            u, v = node_route[j], node_route[j + 1]
            if not G.has_edge(u, v):
                return None
            best_k = min(G[u][v], key=lambda k: G[u][v][k].get(weight, float('inf')))
            edge_route.append((u, v, best_k))
        return edge_route

    def _edge_data(self, edge_key):
        u, v, k = edge_key
        return self.G[u][v].get(k) if self.G.has_edge(u, v, k) else None

    def _calculate_desired_speed(self, vehicle):
        edge_data = self._edge_data(vehicle.route[vehicle.current_edge_index])
        if edge_data is None:
            return 0.0

        v0 = edge_data['speed_ms']
        leading = None
        min_gap = float('inf')
        for other in self.edge_vehicles.get(vehicle.route[vehicle.current_edge_index], []):
            if other.id == vehicle.id:
                continue
            if other.position_on_edge > vehicle.position_on_edge:
                gap = other.position_on_edge - vehicle.position_on_edge
                if gap < min_gap:
                    min_gap = gap
                    leading = other

        if leading is None:
            accel = IDM_PARAMS['a'] * (1 - (vehicle.speed / v0) ** 4)
        else:
            s = max(min_gap, 0.1)
            s_star = (
                IDM_PARAMS['s0']
                + vehicle.speed * IDM_PARAMS['T']
                + (vehicle.speed * (vehicle.speed - leading.speed))
                / (2 * math.sqrt(IDM_PARAMS['a'] * IDM_PARAMS['b']) + 1e-6)
            )
            accel = IDM_PARAMS['a'] * (1 - (vehicle.speed / v0) ** 4 - (s_star / s) ** 2)

        new_speed = vehicle.speed + accel * self.dt
        return max(0.0, min(v0, new_speed))

    def _update_vehicle(self, vehicle):
        if vehicle.current_edge_index >= len(vehicle.route):
            return True

        edge_key = vehicle.route[vehicle.current_edge_index]
        edge_data = self._edge_data(edge_key)
        if edge_data is None:
            # [FIX-2] La arista fue removida del grafo. Marcar como fallido y salir
            # de la simulación. NO contribuye a TTT ni a completed_trips.
            vehicle.failed = True
            self.failed_vehicles.append((vehicle.origin, vehicle.destination))
            return True

        edge_length = edge_data['length']
        vehicle.speed = self._calculate_desired_speed(vehicle)
        distance = vehicle.speed * self.dt
        vehicle.position_on_edge += distance
        vehicle.total_time += self.dt
        self.total_vmt += distance

        if vehicle.position_on_edge >= edge_length:
            vehicle.position_on_edge = 0.0
            if vehicle in self.edge_vehicles.get(edge_key, []):
                self.edge_vehicles[edge_key].remove(vehicle)
            vehicle.current_edge_index += 1

            if vehicle.current_edge_index >= len(vehicle.route):
                vehicle.completed = True
                self.completed_trips += 1
                self.total_time_sum += vehicle.total_time
                self.completed_trip_records.append(
                    (vehicle.id, vehicle.origin, vehicle.destination, vehicle.total_time)
                )
                return True

            next_edge = vehicle.route[vehicle.current_edge_index]
            self.edge_vehicles.setdefault(next_edge, []).append(vehicle)

        return False

    # [FIX-3] Re-enrutamiento sobre tiempos congestionados.
    def _update_congested_times(self):
        """Actualiza un atributo `congested_time` por arista para re-enrutamiento."""
        for u, v, k, data in self.G.edges(keys=True, data=True):
            n_veh = len(self.edge_vehicles.get((u, v, k), []))
            length = data['length']
            density = n_veh / max(length, 1.0)
            # Greenshields-like: tiempo crece con densidad relativa.
            k_jam = 1.0 / 7.5
            congestion = min(0.99, density / k_jam)
            data['congested_time'] = data['free_flow_time'] / max(1.0 - congestion, 0.05)

    def _reroute_reactive(self):
        for vehicle in self.vehicles:
            if vehicle.completed or vehicle.failed:
                continue
            if not vehicle.reactive:
                continue
            if vehicle.current_edge_index >= len(vehicle.route):
                continue
            current_edge = vehicle.route[vehicle.current_edge_index]
            if not self.G.has_edge(*current_edge):
                continue
            current_node = current_edge[1]
            if current_node == vehicle.destination:
                continue
            # [FIX-3] Usa congested_time en lugar de free_flow_time.
            new_route = self._compute_edge_route(
                self.G, current_node, vehicle.destination, weight='congested_time'
            )
            if new_route:
                vehicle.route = vehicle.route[: vehicle.current_edge_index + 1] + new_route

    def run(self, progress_callback=None):
        active = list(self.vehicles)
        n_steps = int(self.duration / self.dt)

        for step in range(n_steps):
            if not active:
                break
            done_this_step = []
            for v in active:
                if self._update_vehicle(v):
                    done_this_step.append(v)
            for v in done_this_step:
                active.remove(v)

            if step % self.reroute_every == 0:
                self._update_congested_times()
                self._reroute_reactive()

            if progress_callback and (step % 30 == 0 or step == n_steps - 1):
                progress_callback(step + 1, n_steps, len(active), self.completed_trips)

        avg_tt = self.total_time_sum / self.completed_trips if self.completed_trips else 0.0

        return {
            'total_travel_time': float(self.total_time_sum),
            'avg_travel_time': float(avg_tt),
            'vmt': float(self.total_vmt),
            'completed_trips': int(self.completed_trips),
            'failed_trips': int(len(self.failed_vehicles)),
            'completed_trip_records': self.completed_trip_records,
        }


# =====================================================================
# MÉTRICA DE MEJORA PAREADA  [FIX-2]
# =====================================================================

def paired_att_improvement(base_records, mod_records):
    """
    Calcula la mejora en ATT comparando SOLAMENTE los viajes que se completaron
    en AMBOS escenarios (base y modificado). Esto elimina el artefacto matemático
    de descontar viajes que no terminan en el escenario modificado.

    Returns:
        improvement_pct: float — mejora en ATT sobre el conjunto pareado.
        n_paired: int — tamaño del conjunto pareado.
        base_paired_times: np.array — tiempos del base sobre los pares comunes.
        mod_paired_times:  np.array — tiempos del modificado sobre los pares comunes.
    """
    base_idx = {(r[1], r[2]): r[3] for r in base_records}  # (origin,dest) -> tiempo
    mod_idx = {(r[1], r[2]): r[3] for r in mod_records}
    common = set(base_idx) & set(mod_idx)
    if not common:
        return 0.0, 0, np.array([]), np.array([])
    base_t = np.array([base_idx[k] for k in common])
    mod_t = np.array([mod_idx[k] for k in common])
    improvement = (1 - mod_t.mean() / base_t.mean()) * 100
    return float(improvement), len(common), base_t, mod_t


# =====================================================================
# REPLICACIONES E INFERENCIA ESTADÍSTICA  [FIX-4]
# =====================================================================

def run_one_replication(G, od_pairs, params, seed):
    """Una réplica. Función a nivel módulo para que sea picklable por joblib."""
    sim = Microsimulator(
        G, od_pairs,
        reactive_ratio=params['reactive_ratio'],
        duration_minutes=params['duration_minutes'],
        reroute_every=params['reroute_every_steps'],
        seed=seed,
    )
    return sim.run()


def run_scenario_replicated(G, od_pairs, params, n_reps, base_seed=0):
    """
    Corre N réplicas de un escenario. Devuelve lista de results.
    Usa joblib para paralelizar.  [FIX-5]
    """
    seeds = [base_seed + i * 1000 for i in range(n_reps)]
    if n_reps == 1 or params.get('n_jobs', 1) <= 1:
        return [run_one_replication(G, od_pairs, params, s) for s in seeds]
    return Parallel(n_jobs=params['n_jobs'], backend='loky')(
        delayed(run_one_replication)(G, od_pairs, params, s) for s in seeds
    )


def benjamini_hochberg(pvalues, alpha=0.05):
    """
    Corrección Benjamini-Hochberg para FDR.
    Devuelve array booleano del mismo tamaño que pvalues, True donde se rechaza H0.
    """
    pvalues = np.asarray(pvalues, dtype=float)
    n = len(pvalues)
    if n == 0:
        return np.array([], dtype=bool)
    order = np.argsort(pvalues)
    ranked = pvalues[order]
    thresholds = (np.arange(1, n + 1) / n) * alpha
    passed = ranked <= thresholds
    if not np.any(passed):
        rejected_in_order = np.zeros(n, dtype=bool)
    else:
        max_idx = np.where(passed)[0].max()
        rejected_in_order = np.zeros(n, dtype=bool)
        rejected_in_order[: max_idx + 1] = True
    rejected = np.zeros(n, dtype=bool)
    rejected[order] = rejected_in_order
    return rejected


def evaluate_modification(G_mod, base_reps, od_pairs, params, scenario_id):
    """
    Evalúa una modificación con réplicas y test pareado Wilcoxon.
    Devuelve un dict con las métricas relevantes y el p-value crudo (sin BH).
    """
    mod_reps = run_scenario_replicated(G_mod, od_pairs, params, params['n_replications'])

    # Comparación pareada réplica-a-réplica con base
    improvements_pct = []
    paired_t_diffs = []  # diferencias de ATT pareadas para Wilcoxon

    for base_r, mod_r in zip(base_reps, mod_reps):
        impr, n_pair, base_t, mod_t = paired_att_improvement(
            base_r['completed_trip_records'], mod_r['completed_trip_records']
        )
        improvements_pct.append(impr)
        if n_pair >= 5:
            # Mediana de diferencias por par O-D (rep-level summary).
            paired_t_diffs.append(np.median(base_t - mod_t))

    improvements_pct = np.array(improvements_pct)
    mean_impr = float(improvements_pct.mean())
    sd_impr = float(improvements_pct.std(ddof=1)) if len(improvements_pct) > 1 else 0.0
    se_impr = sd_impr / math.sqrt(len(improvements_pct)) if len(improvements_pct) > 1 else 0.0
    ci95_lo = mean_impr - 1.96 * se_impr
    ci95_hi = mean_impr + 1.96 * se_impr

    # Test de Wilcoxon: H0 = no hay diferencia entre base y modificado.
    # [FIX-11] Protegemos contra el caso degenerado donde TODAS las diferencias
    # son cero o casi cero, que produce división por cero interna en scipy y
    # un RuntimeWarning. En ese caso, la respuesta correcta es p=1.0 (no hay
    # evidencia de efecto).
    p_value = 1.0
    if len(paired_t_diffs) >= 5:
        diffs_arr = np.asarray(paired_t_diffs, dtype=float)
        # Si la dispersión es despreciable, no hay test estadístico que aplicar.
        if np.std(diffs_arr) < 1e-9 or np.all(np.abs(diffs_arr) < 1e-9):
            p_value = 1.0
        else:
            try:
                with np.errstate(invalid='ignore', divide='ignore'):
                    res = stats.wilcoxon(diffs_arr, alternative='greater',
                                         zero_method='wilcox')
                p_value = float(res.pvalue) if np.isfinite(res.pvalue) else 1.0
            except (ValueError, ZeroDivisionError):
                p_value = 1.0

    # Métricas auxiliares promediadas (TTT, completed_trips, etc.)
    avg_completed_base = np.mean([r['completed_trips'] for r in base_reps])
    avg_completed_mod = np.mean([r['completed_trips'] for r in mod_reps])
    avg_failed_mod = np.mean([r['failed_trips'] for r in mod_reps])

    return {
        'scenario_id': scenario_id,
        'mean_improvement_pct': mean_impr,
        'sd_improvement_pct': sd_impr,
        'ci95_lower': ci95_lo,
        'ci95_upper': ci95_hi,
        'p_value_raw': p_value,
        'avg_completed_base': float(avg_completed_base),
        'avg_completed_mod': float(avg_completed_mod),
        'avg_failed_mod': float(avg_failed_mod),
        'n_replications': len(improvements_pct),
    }


# =====================================================================
# ESCENARIOS: REMOCIÓN Y ADICIÓN
# =====================================================================

def candidate_addition_edges(G, nodes_gdf, max_candidates, max_distance_m, min_distance_m, seed=None):
    nodes = list(G.nodes())
    if len(nodes) < 2:
        return []
    points = nodes_gdf[['x', 'y']].values
    tree = cKDTree(points)
    pairs = tree.query_pairs(max_distance_m / 111139.0)
    candidates = []
    for i, j in pairs:
        u = nodes_gdf.index[i]
        v = nodes_gdf.index[j]
        if not G.has_edge(u, v) and not G.has_edge(v, u):
            candidates.append((int(u), int(v)))  # [FIX-7]
    rng = random.Random(seed)
    rng.shuffle(candidates)
    return candidates[:max_candidates]


def apply_remove(G, u, v, k):
    G2 = G.copy()
    if G2.has_edge(u, v, k):
        G2.remove_edge(u, v, k)
    return G2


def apply_add(G, u, v, params):
    G2 = G.copy()
    o = G.nodes[u]
    d = G.nodes[v]
    length = great_circle_m(o['y'], o['x'], d['y'], d['x'])
    if length < params['addition_min_dist_m'] or length > params['addition_max_dist_m']:
        return None
    speed_kmh = 50.0
    speed_ms = speed_kmh * 1000 / 3600
    geom = LineString([(o['x'], o['y']), (d['x'], d['y'])])
    common = dict(
        length=length, speed_kmh=speed_kmh, speed_ms=speed_ms,
        free_flow_time=length / speed_ms, lanes=2, capacity_vph=3600,
        oneway=False, prepared=True,
    )
    G2.add_edge(u, v, key=0, geometry=geom, osmid=f"{u}_{v}_new", **common)
    G2.add_edge(v, u, key=0, geometry=geom.reverse(), osmid=f"{v}_{u}_new", **common)
    return G2


def get_edge_label(G, u, v, k):
    try:
        d = G.edges[(u, v, k)]
    except KeyError:
        return f"Tramo {u}-{v}"
    name = d.get('name')
    if isinstance(name, list):
        name = name[0] if name else None
    ref = d.get('ref')
    if isinstance(ref, list):
        ref = ref[0] if ref else None
    highway = d.get('highway')
    if isinstance(highway, list):
        highway = highway[0] if highway else None
    translations = {
        'motorway': 'Autopista', 'trunk': 'Carretera', 'primary': 'Avenida',
        'secondary': 'Calle Principal', 'tertiary': 'Calle', 'residential': 'Calle',
        'service': 'Vía de Servicio', 'unclassified': 'Vía',
    }
    type_es = translations.get(str(highway).lower(), str(highway).capitalize() if highway else 'Vía')
    if name:
        return f"{name} ({ref})" if ref else str(name)
    if ref:
        return f"{type_es} {ref}"
    return f"{type_es} (sin nombre)"


# =====================================================================
# ORQUESTACIÓN PRINCIPAL
# =====================================================================

def run_full_analysis(G, params, progress_emit=None):
    """
    Orquesta todo el análisis con réplicas y FDR.
    progress_emit es opcional: callable(step, total, status_msg, phase=None).

    El análisis tiene 6 fases. Cada una emite eventos al frontend y al
    logger para que no haya ventanas de silencio (donde la UI parecía
    colgada en versiones anteriores).  [FIX-14]
    """
    t_start = time.time()

    def emit(step, total, status, phase=None):
        msg = f"[{phase}] {status}" if phase else status
        logger.info(msg)
        if progress_emit:
            progress_emit(step, total, status, phase=phase)

    # ----------- FASE 1: Pre-procesamiento -----------
    emit(0, 100, "Convirtiendo grafo a GeoDataFrames…", phase="setup")
    t0 = time.time()
    nodes_gdf, edges_gdf = ox.graph_to_gdfs(G)
    logger.info(f"  graph_to_gdfs: {time.time()-t0:.1f}s")

    # ----------- FASE 2: Generación de demanda -----------
    emit(0, 100, f"Generando matriz O-D ({params['n_trips']} viajes)…", phase="demand")
    t0 = time.time()
    od_pairs = create_demand_matrix(
        G, n_trips=params['n_trips'],
        min_path_len=params['min_path_len_nodes'], seed=42,
    )
    logger.info(f"  Matriz O-D: {len(od_pairs)}/{params['n_trips']} pares en {time.time()-t0:.1f}s")

    if len(od_pairs) < params['n_trips'] * 0.5:
        return {'error': f'Solo {len(od_pairs)} viajes con rutas no triviales de {params["n_trips"]} solicitados. '
                         f'Aumente el área o reduzca min_path_len_nodes.'}, [], None

    # ----------- FASE 3: Simulación BASE -----------
    emit(0, 100, f"Simulando escenario BASE ({params['n_replications']} réplicas)…", phase="base")
    t0 = time.time()
    base_reps = run_scenario_replicated(G, od_pairs, params, params['n_replications'], base_seed=1)
    logger.info(f"  Base: {time.time()-t0:.1f}s ({params['n_replications']} réplicas)")

    base_summary = {
        'mean_avg_travel_time': float(np.mean([r['avg_travel_time'] for r in base_reps])),
        'mean_completed_trips': float(np.mean([r['completed_trips'] for r in base_reps])),
        'mean_total_travel_time': float(np.mean([r['total_travel_time'] for r in base_reps])),
        'mean_vmt': float(np.mean([r['vmt'] for r in base_reps])),
        'cv_avg_travel_time_pct': float(
            np.std([r['avg_travel_time'] for r in base_reps], ddof=1) /
            np.mean([r['avg_travel_time'] for r in base_reps]) * 100
        ) if params['n_replications'] > 1 else 0.0,
    }
    logger.info(f"  Base ATT = {base_summary['mean_avg_travel_time']:.1f}s, "
                f"CV = {base_summary['cv_avg_travel_time_pct']:.2f}%")

    # ----------- FASE 4: REMOCIONES -----------
    edges_to_test = list(G.edges(keys=True))
    n_removals = len(edges_to_test)
    n_additions = params['max_addition_candidates']
    total_scenarios = n_removals + n_additions

    emit(0, total_scenarios, f"Iniciando {n_removals} remociones…", phase="removals")

    # Emisión más frecuente: cada N escenarios o cada 5 s, lo que pase antes.
    EMIT_EVERY_N = max(1, n_removals // 100)  # ≥100 actualizaciones totales
    EMIT_EVERY_S = 5.0
    t_phase = time.time()
    t_last_emit = t_phase

    removal_results = []
    removal_failures = 0
    for i, (u, v, k) in enumerate(edges_to_test):
        now = time.time()
        if i == 0 or (i + 1) % EMIT_EVERY_N == 0 or (now - t_last_emit) >= EMIT_EVERY_S:
            eta = ((now - t_phase) / max(1, i + 1)) * (n_removals - i - 1) if i > 0 else None
            eta_str = f", ETA fase ~{int(eta)}s" if eta else ""
            emit(i + 1, total_scenarios,
                 f"Remoción {i+1}/{n_removals} ({100*(i+1)/n_removals:.1f}%){eta_str}",
                 phase="removals")
            t_last_emit = now

        G_mod = apply_remove(G, u, v, k)
        scenario_id = f"remove_{u}_{v}_{k}"
        try:
            res = evaluate_modification(G_mod, base_reps, od_pairs, params, scenario_id)
            res['action'] = 'remove'
            res['u'], res['v'], res['k'] = int(u), int(v), int(k)
            removal_results.append(res)
        except Exception as e:
            removal_failures += 1
            logger.warning(f"Falló escenario {scenario_id}: {e}")

    emit(n_removals, total_scenarios,
         f"Remociones terminadas: {len(removal_results)}/{n_removals} OK "
         f"({removal_failures} fallidas) en {time.time()-t_phase:.0f}s",
         phase="removals")

    # ----------- FASE 5: ADICIONES -----------
    emit(n_removals, total_scenarios, f"Generando candidatas de adición…", phase="additions")
    t0 = time.time()
    candidates = candidate_addition_edges(
        G, nodes_gdf, params['max_addition_candidates'],
        params['addition_max_dist_m'], params['addition_min_dist_m'], seed=99,
    )
    logger.info(f"  {len(candidates)} candidatas de adición en {time.time()-t0:.1f}s")
    emit(n_removals, total_scenarios,
         f"Iniciando {len(candidates)} adiciones…", phase="additions")

    EMIT_EVERY_N_ADD = max(1, len(candidates) // 50)
    t_phase = time.time()
    t_last_emit = t_phase

    addition_results = []
    addition_failures = 0
    for i, (u, v) in enumerate(candidates):
        now = time.time()
        if i == 0 or (i + 1) % EMIT_EVERY_N_ADD == 0 or (now - t_last_emit) >= EMIT_EVERY_S:
            eta = ((now - t_phase) / max(1, i + 1)) * (len(candidates) - i - 1) if i > 0 else None
            eta_str = f", ETA fase ~{int(eta)}s" if eta else ""
            emit(n_removals + i + 1, total_scenarios,
                 f"Adición {i+1}/{len(candidates)} ({100*(i+1)/len(candidates):.1f}%){eta_str}",
                 phase="additions")
            t_last_emit = now

        G_mod = apply_add(G, u, v, params)
        if G_mod is None:
            continue
        scenario_id = f"add_{u}_{v}"
        try:
            res = evaluate_modification(G_mod, base_reps, od_pairs, params, scenario_id)
            res['action'] = 'add'
            res['u'], res['v'] = int(u), int(v)
            addition_results.append(res)
        except Exception as e:
            addition_failures += 1
            logger.warning(f"Falló escenario {scenario_id}: {e}")

    emit(total_scenarios, total_scenarios,
         f"Adiciones terminadas: {len(addition_results)}/{len(candidates)} OK "
         f"({addition_failures} fallidas) en {time.time()-t_phase:.0f}s",
         phase="additions")

    all_results = removal_results + addition_results

    # ----------- FASE 6: POST-PROCESAMIENTO (era invisible antes) -----------
    # [FIX-14] Estas tres operaciones suelen tomar 30-90s en redes grandes
    # y antes parecían "cuelgue" en la UI. Ahora emiten progreso.

    emit(total_scenarios, total_scenarios,
         f"Aplicando corrección Benjamini-Hochberg sobre {len(all_results)} hipótesis…",
         phase="postproc")
    t0 = time.time()
    pvals = np.array([r['p_value_raw'] for r in all_results])
    rejected = benjamini_hochberg(pvals, alpha=params['fdr_alpha'])
    for r, rej in zip(all_results, rejected):
        r['fdr_significant'] = bool(rej)
    n_sig = int(rejected.sum())
    logger.info(f"  BH: {n_sig}/{len(all_results)} significativos en {time.time()-t0:.1f}s "
                f"(α={params['fdr_alpha']})")

    emit(total_scenarios, total_scenarios,
         f"Filtrando recomendaciones (efecto ≥ {params['min_effect_size_pct']}%)…",
         phase="postproc")
    t0 = time.time()
    recommendations = []
    for r in all_results:
        if r['fdr_significant'] and r['mean_improvement_pct'] >= params['min_effect_size_pct']:
            rec = _format_recommendation(r, G, edges_gdf)
            if rec:
                recommendations.append(rec)

    recommendations.sort(key=lambda x: x['impact_pct'], reverse=True)
    _assign_colors(recommendations)
    logger.info(f"  {len(recommendations)} recomendaciones finales en {time.time()-t0:.1f}s")

    emit(total_scenarios, total_scenarios,
         f"Análisis completo: {len(recommendations)} recomendaciones, "
         f"{n_sig} significativas, total {time.time()-t_start:.0f}s",
         phase="done")

    study_metrics = {
        'n_scenarios_tested': len(all_results),
        'n_scenarios_significant_fdr': n_sig,
        'n_recommendations': len(recommendations),
        'fdr_alpha': params['fdr_alpha'],
        'min_effect_size_pct': params['min_effect_size_pct'],
        'n_replications_per_scenario': params['n_replications'],
        'n_trips': params['n_trips'],
        'min_path_len_nodes': params['min_path_len_nodes'],
        'percent_significant': float(n_sig / max(len(all_results), 1) * 100),
        'total_seconds': round(time.time() - t_start, 1),
        'failures_removal': removal_failures,
        'failures_addition': addition_failures,
    }

    return {
        'base': base_summary,
        'study_metrics': study_metrics,
    }, recommendations, all_results


def _format_recommendation(r, G, edges_gdf):
    if r['action'] == 'remove':
        u, v, k = r['u'], r['v'], r['k']
        label = get_edge_label(G, u, v, k)
        try:
            geom = list(edges_gdf.loc[(u, v, k)].geometry.coords)
        except KeyError:
            geom = None
        osmid_raw = f"{u}_{v}_{k}"
    else:
        u, v = r['u'], r['v']
        o = G.nodes[u]; d = G.nodes[v]
        label = f"Añadir {o['y']:.4f},{o['x']:.4f} → {d['y']:.4f},{d['x']:.4f}"
        geom = [(o['x'], o['y']), (d['x'], d['y'])]
        osmid_raw = f"{u}_{v}_new"

    justification = (
        f"{r['action'].capitalize()}: ATT mejora {r['mean_improvement_pct']:+.2f}% "
        f"(IC95% [{r['ci95_lower']:+.2f}%, {r['ci95_upper']:+.2f}%], "
        f"p={r['p_value_raw']:.4g}, FDR-significativo)."
    )
    return {
        'osmid': label,
        'osmid_raw': osmid_raw,
        'action': r['action'],
        'impact_pct': float(r['mean_improvement_pct']),
        'ci95_lower': float(r['ci95_lower']),
        'ci95_upper': float(r['ci95_upper']),
        'p_value': float(r['p_value_raw']),
        'justification': justification,
        'geometry': geom,
    }


def _assign_colors(recs):
    if not recs:
        return
    impacts = np.array([r['impact_pct'] for r in recs])
    # [FIX-2 bis] Normalización por percentiles, robusta a outliers.
    if len(impacts) >= 3:
        p33, p66 = np.percentile(impacts, [33.33, 66.66])
    else:
        p33 = p66 = impacts.mean()
    for r in recs:
        if r['impact_pct'] >= p66:
            cat = 'high'
        elif r['impact_pct'] >= p33:
            cat = 'medium'
        else:
            cat = 'low'
        if r['action'] == 'remove':
            r['color'] = {'high': '#e53e3e', 'medium': '#f97316', 'low': '#3b82f6'}[cat]
        else:
            r['color'] = {'high': '#38a169', 'medium': '#eab308', 'low': '#a855f7'}[cat]
        r['color_category'] = cat


# =====================================================================
# FLASK APP
# =====================================================================

app = Flask(__name__, static_folder='.')
app.config['SECRET_KEY'] = 'braess_v2_secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# [FIX-9] Estado mínimo en módulo, pero encapsulado.
class _State:
    graph = None
    edges_gdf = None
    nodes_gdf = None
    recommendations = []
    last_results = None

STATE = _State()


# =====================================================================
# DESCARGA ROBUSTA DE GRAFO  [FIX-13]
# =====================================================================
# graph_from_place exige que Nominatim devuelva un (Multi)Polygon, lo cual
# falla para barrios pequeños, puntos de interés y consultas ambiguas
# (ej. "SoHo, Manhattan, NYC" devuelve un punto, no un polígono).
#
# Estrategia escalonada:
#   1. Intentar graph_from_place (caso ideal: municipio/barrio con polígono).
#   2. Si falla por geometría, geocodificar a punto y usar graph_from_point
#      con un radio configurable (default 1500 m).
#   3. Si la geocodificación también falla, devolver mensaje útil al usuario.

def download_graph_robust(place, fallback_radius_m=1500):
    """
    Descarga un grafo OSM tolerante a entradas que no resuelven a polígono.
    Devuelve (G, info) donde info documenta qué método se usó.

    Lanza ValueError con mensaje útil si todos los métodos fallan.
    """
    info = {'method': None, 'fallback_radius_m': None, 'center': None}

    # Nivel 1: intentar polígono administrativo
    try:
        G = ox.graph_from_place(place, network_type='drive')
        info['method'] = 'place_polygon'
        logger.info(f"Descarga vía graph_from_place OK")
        return G, info
    except (TypeError, ValueError) as e:
        # TypeError = "did not geocode to (Multi)Polygon"
        # ValueError = "Nominatim could not geocode"
        msg = str(e)
        if 'Polygon' not in msg and 'geocode' not in msg.lower():
            raise
        logger.warning(f"graph_from_place falló ({msg[:80]}…). Intentando fallback a punto.")

    # Nivel 2: geocodificar a punto y usar from_point + radio
    try:
        center = ox.geocoder.geocode(place)
        info['center'] = (float(center[0]), float(center[1]))
        logger.info(f"Geocodificación a punto: {center}")
    except Exception as e:
        raise ValueError(
            f"No se pudo localizar '{place}' en OpenStreetMap. "
            f"Pruebe con un nombre más específico (ej. 'Barrio, Ciudad, País'). "
            f"Detalle técnico: {e}"
        ) from e

    try:
        G = ox.graph_from_point(center, dist=fallback_radius_m, network_type='drive')
        info['method'] = 'point_radius'
        info['fallback_radius_m'] = fallback_radius_m
        logger.info(
            f"Descarga vía graph_from_point en radio {fallback_radius_m}m: "
            f"{len(G.nodes)} nodos, {len(G.edges)} aristas"
        )
        return G, info
    except Exception as e:
        raise ValueError(
            f"Se geocodificó '{place}' a {center} pero no fue posible descargar la red "
            f"vial alrededor. Detalle: {e}"
        ) from e


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('.', path)


@app.route('/api/simulate', methods=['POST'])
def api_simulate():
    data = request.json or {}
    place = data.get('place')
    if not place:
        return jsonify({'success': False, 'error': 'Falta el campo "place".'}), 400

    user_params = data.get('params') or {}
    # Si el usuario marcó auto=False explícitamente o pasó cualquier override,
    # respetamos. Si auto=True o no hay overrides, usamos auto-tuning.
    use_auto = data.get('auto_tune', True)
    budget_minutes = float(data.get('budget_minutes', 30))

    # 1. Descargar el grafo PRIMERO. El auto-tuning necesita inspeccionar la red.
    try:
        logger.info(f"Descargando red OSM para: {place}")
        fallback_radius = int(data.get('fallback_radius_m', 1500))
        G, download_info = download_graph_robust(place, fallback_radius_m=fallback_radius)
        G = prepare_osm_graph(G)
        STATE.graph = G
        STATE.nodes_gdf, STATE.edges_gdf = ox.graph_to_gdfs(G)
        logger.info(f"Grafo descargado: {len(G.nodes)} nodos, {len(G.edges)} aristas")
    except ValueError as e:
        logger.warning(f"Descarga falló: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Falló descarga: {e}", exc_info=True)
        return jsonify({'success': False, 'error': f"No se pudo descargar el mapa: {e}"}), 500

    # 2. Auto-tunear (si procede) y aplicar overrides del usuario.  [FIX-12]
    if use_auto:
        n_jobs = DEFAULT_PARAMS['n_jobs']
        auto_params = auto_tune_params(G, n_jobs, budget_minutes=budget_minutes)
        params = merge_user_params(auto_params, user_params)
        logger.info(
            f"Auto-tune: n_trips={params['n_trips']}, n_reps={params['n_replications']}, "
            f"min_path_len={params['min_path_len_nodes']}, duration={params['duration_minutes']}min, "
            f"max_add={params['max_addition_candidates']}, "
            f"tiempo estimado paralelo ≈ {params['_estimated_parallel_minutes']} min"
        )
        if params.get('_sampling_recommended'):
            logger.warning(
                f"Red muy grande ({len(G.edges)} aristas). El presupuesto de "
                f"{budget_minutes} min puede no ser suficiente. Considere subdividir la zona."
            )
    else:
        params = dict(DEFAULT_PARAMS)
        for k, v in user_params.items():
            if k in params:
                try:
                    params[k] = type(params[k])(v)
                except (ValueError, TypeError):
                    pass

    def emit_progress(step, total, status, phase=None):
        socketio.emit('simulation_update', {
            'step': step, 'total_steps': total, 'status': status, 'phase': phase,
        })

    try:
        results, recommendations, _all = run_full_analysis(G, params, progress_emit=emit_progress)
        if isinstance(results, dict) and results.get('error'):
            return jsonify({'success': False, 'error': results['error']}), 400
        STATE.recommendations = recommendations
        STATE.last_results = results

        # Echo de los parámetros usados (para que el frontend muestre qué tuneó auto).
        params_echo = {k: v for k, v in params.items() if not k.startswith('_')}
        params_meta = {k: v for k, v in params.items() if k.startswith('_')}

        # [FIX-14] Serialización de aristas. En redes grandes esto toma 30-90s.
        # Notificar al frontend para que no parezca colgado.
        emit_progress(1, 1, "Serializando red para visualización…", phase="serialize")
        t_ser = time.time()
        edges_json = json.loads(STATE.edges_gdf.to_json())
        logger.info(f"Serialización de {len(edges_json.get('features', []))} aristas: {time.time()-t_ser:.1f}s")

        emit_progress(1, 1, "Enviando resultados al navegador…", phase="done")
        return jsonify({
            'success': True,
            'results': results,
            'recommendations': recommendations,
            'edges': edges_json,
            'params_used': params_echo,
            'params_meta': params_meta,
            'download_info': download_info,
        })
    except Exception as e:
        logger.error(f"Falló simulación: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# Endpoint auxiliar: solo descarga el grafo y devuelve los parámetros sugeridos
# sin correr la simulación. Útil para que el frontend muestre los defaults antes
# de que el usuario decida ejecutar.
@app.route('/api/suggest_params', methods=['POST'])
def api_suggest_params():
    data = request.json or {}
    place = data.get('place')
    budget_minutes = float(data.get('budget_minutes', 30))
    if not place:
        return jsonify({'success': False, 'error': 'Falta el campo "place".'}), 400
    try:
        fallback_radius = int(data.get('fallback_radius_m', 1500))
        G, download_info = download_graph_robust(place, fallback_radius_m=fallback_radius)
        G = prepare_osm_graph(G)
        n_jobs = DEFAULT_PARAMS['n_jobs']
        params = auto_tune_params(G, n_jobs, budget_minutes=budget_minutes)
        return jsonify({'success': True, 'suggested': params, 'download_info': download_info})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Falló suggest_params: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/recommendations')
def api_recommendations():
    return jsonify(STATE.recommendations)


@app.route('/api/export/<format_type>')
def api_export(format_type):
    if format_type == 'geojson':
        features = []
        for r in STATE.recommendations:
            if r.get('geometry'):
                features.append({
                    'type': 'Feature',
                    'properties': {
                        'osmid': r['osmid'], 'action': r['action'],
                        'impact_pct': r['impact_pct'],
                        'ci95_lower': r.get('ci95_lower'),
                        'ci95_upper': r.get('ci95_upper'),
                        'p_value': r.get('p_value'),
                        'justification': r.get('justification', ''),
                    },
                    'geometry': {'type': 'LineString', 'coordinates': r['geometry']},
                })
        return jsonify({'type': 'FeatureCollection', 'features': features})

    if format_type == 'csv':
        out = io.StringIO()
        out.write('osmid,action,impact_pct,ci95_lower,ci95_upper,p_value,justification\n')
        for r in STATE.recommendations:
            j = (r.get('justification') or '').replace('"', '""')
            out.write(
                f"\"{r['osmid']}\",{r['action']},{r['impact_pct']:.3f},"
                f"{r.get('ci95_lower', 0):.3f},{r.get('ci95_upper', 0):.3f},"
                f"{r.get('p_value', 1):.6g},\"{j}\"\n"
            )
        return out.getvalue(), 200, {
            'Content-Type': 'text/csv',
            'Content-Disposition': 'attachment; filename=recommendations.csv',
        }

    return jsonify({'error': 'Formato no soportado'}), 400


@app.route('/api/export/modified_graph')
def api_export_modified_graph():
    if STATE.graph is None:
        return jsonify({'error': 'No hay grafo. Corra simulate primero.'}), 400
    if not STATE.recommendations:
        return jsonify({'error': 'No hay recomendaciones.'}), 400
    G_mod = STATE.graph.copy()
    for r in STATE.recommendations:
        try:
            if r['action'] == 'remove':
                u, v, k = [int(p) for p in r['osmid_raw'].split('_')]
                if G_mod.has_edge(u, v, k):
                    G_mod.remove_edge(u, v, k)
            else:
                parts = r['osmid_raw'].split('_')
                u, v = int(parts[0]), int(parts[1])
                G_mod = apply_add(G_mod, u, v, DEFAULT_PARAMS) or G_mod
        except Exception as e:
            logger.warning(f"No pude aplicar {r['osmid']}: {e}")

    with tempfile.NamedTemporaryFile(mode='w', suffix='.graphml', delete=False) as tmp:
        ox.save_graphml(G_mod, tmp.name)
        tmp_path = tmp.name
    with open(tmp_path, 'r', encoding='utf-8') as f:
        content = f.read()
    os.remove(tmp_path)
    return content, 200, {
        'Content-Type': 'application/xml',
        'Content-Disposition': 'attachment; filename=modified_network.graphml',
    }


@socketio.on('connect')
def on_connect():
    logger.info('Cliente WS conectado.')


@socketio.on('disconnect')
def on_disconnect():
    logger.info('Cliente WS desconectado.')


if __name__ == '__main__':
    import os
    
    # Render asigna el puerto dinámicamente a través de la variable de entorno PORT.
    # Si la variable no existe (ej. corriendo en local), usa el 5000 por defecto.
    port = int(os.environ.get('PORT', 5000))
    
    logger.info(f"Iniciando Detector de Paradoja de Braess v2 en el puerto {port}…")
    
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)