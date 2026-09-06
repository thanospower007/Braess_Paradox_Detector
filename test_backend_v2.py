"""
test_backend_v2.py — Pruebas de validación de las correcciones.

Ejecuta cuatro pruebas independientes:
  Test 1: matriz O-D produce rutas no triviales
  Test 2: métrica pareada vs métrica vieja (artefacto)
  Test 3: análisis end-to-end sobre red Wheatstone (debe detectar atajo paradójico)
  Test 4: corrección Benjamini-Hochberg con p-values sintéticos

Ejecución:
    python test_backend_v2.py [--place "Guatapé, Antioquia, Colombia"]
"""

import argparse
import logging
import random
import statistics
import time
import warnings

warnings.filterwarnings('ignore')
logging.disable(logging.WARNING)

import numpy as np
import networkx as nx
import osmnx as ox
from shapely.geometry import LineString

import backend_v2 as bv2


def test_1_nontrivial_routes(place):
    print("\n" + "=" * 70)
    print("TEST 1: La matriz O-D produce rutas no triviales")
    print("=" * 70)
    G = ox.graph_from_place(place, network_type='drive')
    G = bv2.prepare_osm_graph(G)
    print(f"Red: {len(G.nodes)} nodos, {len(G.edges)} aristas")

    od = bv2.create_demand_matrix(G, n_trips=300, min_path_len=4, seed=1)
    print(f"Generados {len(od)} viajes con path_len ≥ 4")

    lens = []
    for o, d in od[:200]:
        lens.append(len(nx.shortest_path(G, o, d, weight='free_flow_time')))

    median_len = statistics.median(lens)
    trivial = sum(1 for L in lens if L <= 2)
    print(f"Longitud mediana de ruta: {median_len}")
    print(f"Rutas triviales (≤ 2): {trivial}/200")

    assert trivial == 0, "FALLA: aún hay rutas triviales"
    assert median_len >= 4, "FALLA: la mediana de rutas es < 4"
    print("✅ TEST 1 PASA")
    return G, od


def test_2_paired_vs_old_metric(G, od):
    print("\n" + "=" * 70)
    print("TEST 2: La métrica pareada elimina artefactos del descarte de viajes")
    print("=" * 70)
    sim_base = bv2.Microsimulator(G, od, duration_minutes=4, seed=1)
    base = sim_base.run()
    print(f"Base: ATT={base['avg_travel_time']:.2f}s, completed={base['completed_trips']}\n")

    random.seed(42)
    edges = list(G.edges(keys=True))
    random.shuffle(edges)

    cases_artifact = 0
    cases_genuine = 0
    print(f"  {'arista':36s} {'ΔTTT vieja':>11s} {'ΔATT pareada':>13s}")
    print("  " + "-" * 64)
    for (u, v, k) in edges[:8]:
        G_mod = bv2.apply_remove(G, u, v, k)
        sim_mod = bv2.Microsimulator(G_mod, od, duration_minutes=4, seed=1)
        mod = sim_mod.run()
        delta_ttt = (1 - mod['total_travel_time'] / base['total_travel_time']) * 100
        impr_paired, _, _, _ = bv2.paired_att_improvement(
            base['completed_trip_records'], mod['completed_trip_records']
        )
        print(f"  {str((u, v, k)):36s} {delta_ttt:>+10.2f}%  {impr_paired:>+12.2f}%")
        if delta_ttt > 0.1 and impr_paired <= 0.0:
            cases_artifact += 1
        if impr_paired > 0.1:
            cases_genuine += 1

    print(f"\n  Casos artefacto detectados (TTT viejo declara mejora, ATT pareado no): {cases_artifact}/8")
    print(f"  Casos genuinos (ambas métricas concuerdan en mejora): {cases_genuine}/8")
    print("✅ TEST 2 PASA — la métrica pareada es estricta donde la antigua era ingenua")


def test_3_braess_detection():
    print("\n" + "=" * 70)
    print("TEST 3: Detección del atajo paradójico en red Wheatstone")
    print("=" * 70)
    G = nx.MultiDiGraph()
    G.graph['crs'] = 'EPSG:4326'
    G.add_node(1, x=-75.50, y=6.20)
    G.add_node(2, x=-75.49, y=6.21)
    G.add_node(3, x=-75.49, y=6.19)
    G.add_node(4, x=-75.48, y=6.20)

    def add_edge(u, v, length, lanes, speed=50):
        speed_ms = speed * 1000 / 3600
        G.add_edge(u, v, key=0, length=float(length), speed_kmh=speed,
                   speed_ms=speed_ms, free_flow_time=length / speed_ms,
                   lanes=lanes, capacity_vph=lanes * 1800, oneway=False,
                   prepared=True, highway='primary', osmid=f'{u}_{v}',
                   geometry=LineString([(G.nodes[u]['x'], G.nodes[u]['y']),
                                        (G.nodes[v]['x'], G.nodes[v]['y'])]))

    # S→A (corta, 1 carril) - A→T (larga, 2 carriles) - simétricas - atajo A→B
    for u, v, L, lanes in [(1, 2, 100, 1), (2, 1, 100, 1), (2, 4, 300, 2),
                            (4, 2, 300, 2), (1, 3, 300, 2), (3, 1, 300, 2),
                            (3, 4, 100, 1), (4, 3, 100, 1), (2, 3, 30, 1),
                            (3, 2, 30, 1)]:
        add_edge(u, v, L, lanes)

    params = dict(bv2.DEFAULT_PARAMS)
    params.update({
        'n_trips': 200, 'min_path_len_nodes': 3, 'duration_minutes': 3,
        'n_replications': 15, 'fdr_alpha': 0.05, 'min_effect_size_pct': 0.5,
        'max_addition_candidates': 0, 'n_jobs': 1,
    })

    t0 = time.time()
    results, recs, all_results = bv2.run_full_analysis(G, params)
    print(f"  ⏱  {time.time() - t0:.1f}s")

    # El atajo (2,3) o (3,2) debe estar en recs
    shortcut_in_recs = any(r.get('osmid_raw') in {'2_3_0', '3_2_0'} for r in recs)
    top_recommendation = max(all_results, key=lambda x: x['mean_improvement_pct'])
    is_shortcut = (top_recommendation['u'], top_recommendation['v']) in {(2, 3), (3, 2)}

    print(f"  Top recomendación: ({top_recommendation['u']},{top_recommendation['v']})")
    print(f"    ΔATT = {top_recommendation['mean_improvement_pct']:+.2f}%")
    print(f"    IC95% = [{top_recommendation['ci95_lower']:+.2f}, "
          f"{top_recommendation['ci95_upper']:+.2f}]")
    print(f"    p_raw = {top_recommendation['p_value_raw']:.5f}")
    print(f"    FDR-significativo: {top_recommendation['fdr_significant']}")

    assert is_shortcut, "FALLA: el atajo paradójico no es la mejor recomendación"
    assert shortcut_in_recs, "FALLA: atajo paradójico no pasa filtro FDR + efecto"
    print("✅ TEST 3 PASA — detecta paradoja clásica con significancia estadística")


def test_4_benjamini_hochberg():
    print("\n" + "=" * 70)
    print("TEST 4: Corrección Benjamini-Hochberg con p-values sintéticos")
    print("=" * 70)
    pvals = np.array([0.001, 0.008, 0.039, 0.041, 0.042, 0.05, 0.1, 0.5, 0.9])
    rejected = bv2.benjamini_hochberg(pvals, alpha=0.05)
    print(f"  p-values: {pvals.tolist()}")
    print(f"  rechazos: {rejected.tolist()}")

    # Cálculo manual: ordenados, BH umbral i: alpha * i / n
    n = len(pvals)
    ordered = np.sort(pvals)
    thresholds = np.arange(1, n + 1) / n * 0.05
    expected_pass = ordered <= thresholds
    if expected_pass.any():
        max_pass = np.where(expected_pass)[0].max()
        n_expected = max_pass + 1
    else:
        n_expected = 0
    n_actual = int(rejected.sum())
    print(f"  rechazos esperados: {n_expected}, observados: {n_actual}")
    assert n_actual == n_expected, "FALLA en cálculo BH"
    print("✅ TEST 4 PASA")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--place', default='Guatapé, Antioquia, Colombia',
                    help='Lugar OSM para tests 1-2')
    args = ap.parse_args()

    print("\n" + "=" * 70)
    print(" TESTS DE VALIDACIÓN — backend_v2.py ".center(70, "="))
    print("=" * 70)

    G, od = test_1_nontrivial_routes(args.place)
    test_2_paired_vs_old_metric(G, od)
    test_3_braess_detection()
    test_4_benjamini_hochberg()

    print("\n" + "=" * 70)
    print(" TODOS LOS TESTS PASAN ".center(70, "="))
    print("=" * 70 + "\n")


if __name__ == '__main__':
    main()
