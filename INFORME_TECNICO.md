# 🔬 Informe Técnico Detallado - Sistema de Detección de Paradoja de Braess

## 📑 Índice
1. [Resumen Ejecutivo](#resumen-ejecutivo)
2. [Fundamentos Teóricos](#fundamentos-teóricos)
3. [Análisis de Código por Archivo](#análisis-de-código-por-archivo)
4. [Algoritmos Implementados](#algoritmos-implementados)
5. [Flujo de Datos Completo](#flujo-de-datos-completo)
6. [Métricas y Cálculos](#métricas-y-cálculos)

---

## 📊 Resumen Ejecutivo

### Propósito del Sistema

Este sistema implementa un **simulador de tráfico microscópico** para detectar instancias de la Paradoja de Braess en redes viales reales. Utiliza:

- **Modelo de tráfico**: IDM (Intelligent Driver Model)
- **Fuente de datos**: OpenStreetMap vía OSMnx
- **Método de análisis**: Fuerza bruta para remoción, muestreo para adición
- **Visualización**: Leaflet.js con codificación de colores normalizada

### Métricas Clave

El sistema evalúa 4 métricas principales:

1. **Total Travel Time (TTT)**: Suma de tiempos de viaje de todos los vehículos
2. **Average Travel Time (ATT)**: TTT / número de viajes completados
3. **Vehicle Miles Traveled (VMT)**: Distancia total recorrida
4. **Completed Trips**: Número de viajes finalizados

---

## 🎓 Fundamentos Teóricos

### La Paradoja de Braess

**Definición formal**:
> En una red de flujo con usuarios egoístas que minimizan su costo individual, agregar un enlace puede aumentar el costo total del sistema en equilibrio de Nash.

**Ejemplo clásico**:

```
Red Original:
    A -----(x)-----> B
    |                |
   (45)            (45)
    |                |
    C -----(x)-----> D

Donde:
- (x) = tiempo variable según flujo
- (45) = tiempo constante 45 min

Equilibrio: 50% toma A→B→D, 50% toma A→C→D
Tiempo promedio: 1.5 horas

Red con enlace B→C (tiempo 0):
    A -----(x)-----> B
    |                |↓
   (45)            (0)
    |              ↓ |
    C -----(x)-----> D

Nuevo equilibrio: Todos toman A→B→C→D
Tiempo promedio: 2 horas (¡PEOR!)
```

### Modelo IDM (Intelligent Driver Model)

**Ecuación de aceleración**:

```
dv/dt = a [1 - (v/v₀)⁴ - (s*/s)²]

Donde:
- v: velocidad actual
- v₀: velocidad deseada
- a: aceleración máxima
- s: distancia al vehículo adelante
- s*: distancia deseada

s* = s₀ + vT + (vΔv)/(2√(ab))

Donde:
- s₀: distancia mínima
- T: tiempo de reacción
- Δv: diferencia de velocidad con líder
- b: desaceleración confortable
```

**Parámetros usados**:
- `T = 1.5 s`: Tiempo de reacción típico
- `a = 1.0 m/s²`: Aceleración urbana
- `b = 1.5 m/s²`: Frenado confortable
- `s₀ = 2.0 m`: Espacio mínimo

---

## 💻 Análisis de Código por Archivo

### 1. backend.py (896 líneas)

#### Sección 1: Importaciones y Configuración (Líneas 1-63)

```python
# Detección automática de GPU
try:
    import cupy as cp
    np = cp
    USE_CUPY = True
except ImportError:
    import numpy as np
    USE_CUPY = False
```

**Explicación**:
- CuPy es un drop-in replacement de NumPy que usa GPU NVIDIA
- Si está disponible, acelera operaciones de arrays 10-100x
- Si no, usa NumPy estándar (CPU)

**Variables globales**:
```python
current_graph = None          # Grafo de NetworkX
current_nodes_gdf = None      # GeoDataFrame de nodos
current_edges_gdf = None      # GeoDataFrame de aristas
simulation_results = {}       # Resultados de simulación
recommendations = []          # Lista de recomendaciones
```

#### Sección 2: Preparación de Red (Líneas 65-91)

**Función `prepare_osm_graph(G)`**:

```python
def prepare_osm_graph(G):
    for u, v, k, data in G.edges(keys=True, data=True):
        # 1. Obtener velocidad según tipo de vía
        speed_kmh = get_speed_kmh(data.get('highway'))
        
        # 2. Convertir a m/s
        data['speed_ms'] = speed_kmh * 1000 / 3600
        
        # 3. Calcular tiempo de flujo libre
        data['free_flow_time'] = length / speed_ms
        
        # 4. Estimar capacidad
        data['capacity'] = lanes * 1800  # veh/hora
        
        # 5. Crear geometría si no existe
        if 'geometry' not in data:
            data['geometry'] = LineString([...])
```

**Velocidades por tipo de vía**:
```python
DEFAULT_SPEEDS = {
    'motorway': 90,    # Autopista
    'trunk': 80,       # Vía rápida
    'primary': 60,     # Avenida principal
    'secondary': 50,   # Calle principal
    'tertiary': 40,    # Calle secundaria
    'residential': 30, # Calle residencial
    'service': 20,     # Vía de servicio
    'default': 30      # Por defecto
}
```

#### Sección 3: Generación de Demanda (Líneas 91-102)

**Función `create_demand_matrix(G)`**:

```python
def create_demand_matrix(G):
    od_pairs = []
    for u, v, k in G.edges(keys=True):
        # 6 viajes por arista
        od_pairs.extend([(u, v)] * 6)
    
    random.shuffle(od_pairs)
    return od_pairs
```

**Justificación**:
- **6 viajes por arista**: Balance entre realismo y tiempo de cómputo
- **Shuffle**: Evita patrones artificiales de entrada
- **Origen = inicio de arista, Destino = fin**: Simplificación razonable

#### Sección 4: Clase Vehicle (Líneas 102-114)

**Atributos**:

```python
class Vehicle:
    id: int                    # Identificador único
    origin: int                # Nodo de origen
    destination: int           # Nodo de destino
    route: List[Tuple]         # Lista de aristas (u, v, k)
    current_edge_index: int    # Posición en ruta
    position_on_edge: float    # Metros en arista actual
    speed: float               # Velocidad actual (m/s)
    total_time: float          # Tiempo acumulado (s)
    reactive: bool             # ¿Recalcula ruta?
```

**Tipos de vehículos**:
- **Reactivos (30%)**: Recalculan ruta cada 30 pasos según congestión
- **No reactivos (70%)**: Mantienen ruta inicial

#### Sección 5: Clase Microsimulator (Líneas 116-327)

**Método `__init__`**:

```python
def __init__(self, G, od_pairs, reactive_ratio=0.3, duration_minutes=10, dt=1.0):
    # 1. Inicializar estructuras
    self.edge_vehicles = {}    # Vehículos por arista
    self.edge_congestion = {}  # Congestión por arista
    
    # 2. Crear vehículos
    for origin, dest in od_pairs:
        # Calcular ruta más corta
        route = nx.shortest_path(G, origin, dest, weight='free_flow_time')
        
        # Convertir a aristas
        edge_route = [(route[i], route[i+1], k) for i in range(len(route)-1)]
        
        # Crear vehículo
        vehicle = Vehicle(id, origin, dest, edge_route, reactive)
        
        # Asignar a primera arista
        self.edge_vehicles[edge_route[0]].append(vehicle)
```

**Método `calculate_desired_speed`**:

```python
def calculate_desired_speed(self, vehicle):
    # 1. Obtener velocidad deseada de la arista
    v0 = edge_data['speed_ms']
    
    # 2. Encontrar vehículo líder
    leading_vehicle = None
    min_gap = float('inf')
    for other in vehicles_on_edge:
        if other.position_on_edge > vehicle.position_on_edge:
            gap = other.position_on_edge - vehicle.position_on_edge
            if gap < min_gap:
                min_gap = gap
                leading_vehicle = other
    
    # 3. Calcular aceleración IDM
    if leading_vehicle is None:
        # Flujo libre
        acceleration = a * (1 - (v/v0)**4)
    else:
        # Car-following
        s = min_gap
        s_star = s0 + v*T + (v*Δv)/(2*√(a*b))
        acceleration = a * (1 - (v/v0)**4 - (s_star/s)**2)
    
    # 4. Actualizar velocidad
    new_speed = v + acceleration * dt
    return max(0, min(v0, new_speed))
```

**Método `update_vehicle_position`**:

```python
def update_vehicle_position(self, vehicle):
    # 1. Calcular velocidad deseada
    vehicle.speed = self.calculate_desired_speed(vehicle)
    
    # 2. Actualizar posición
    distance = vehicle.speed * self.dt
    vehicle.position_on_edge += distance
    vehicle.total_time += self.dt
    self.total_vmt += distance
    
    # 3. Verificar si completó arista
    if vehicle.position_on_edge >= edge_length:
        # Remover de arista actual
        self.edge_vehicles[current_edge].remove(vehicle)
        
        # Avanzar a siguiente arista
        vehicle.current_edge_index += 1
        
        # Verificar si completó ruta
        if vehicle.current_edge_index >= len(vehicle.route):
            self.completed_trips += 1
            self.total_time_sum += vehicle.total_time
            return True  # Vehículo completado
        
        # Agregar a siguiente arista
        next_edge = vehicle.route[vehicle.current_edge_index]
        self.edge_vehicles[next_edge].append(vehicle)
    
    return False
```

**Método `run`**:

```python
def run(self):
    total_steps = int(self.duration / self.dt)  # e.g., 600 pasos para 10 min
    
    for step in range(total_steps):
        # 1. Actualizar todos los vehículos
        for vehicle in active_vehicles:
            if self.update_vehicle_position(vehicle):
                vehicles_to_remove.append(vehicle)
        
        # 2. Remover vehículos completados
        for vehicle in vehicles_to_remove:
            active_vehicles.remove(vehicle)
        
        # 3. Rerouting cada 30 pasos
        if step % 30 == 0:
            self.reroute_reactive_vehicles()
        
        # 4. Calcular congestión
        self.calculate_congestion()
        
        # 5. Emitir progreso (cada 5 pasos)
        if step % 5 == 0:
            socketio.emit('simulation_update', {...})
    
    return {
        'total_travel_time': self.total_time_sum,
        'avg_travel_time': self.total_time_sum / self.completed_trips,
        'vmt': self.total_vmt,
        'completed_trips': self.completed_trips
    }
```

#### Sección 6: Función Principal `run_simulation` (Líneas 399-623)

**Fase 1: Simulación Base**

```python
# Crear matriz de demanda
od_pairs = create_demand_matrix(G)  # 6 viajes × num_aristas

# Ejecutar simulación base
sim_base = Microsimulator(G, od_pairs)
base_results = sim_base.run()
```

**Fase 2: Prueba de Remoción (Fuerza Bruta)**

```python
edges_to_test = list(G.edges(keys=True))  # Todas las aristas

for edge_key in edges_to_test:
    # Copiar grafo
    G_mod = G.copy()
    
    # Remover arista
    G_mod.remove_edge(*edge_key)
    
    # Simular
    sim_mod = Microsimulator(G_mod, od_pairs)
    
    # Verificar que no se desconectó mucho
    if len(sim_mod.vehicles) >= 0.9 * len(sim_base.vehicles):
        result = sim_mod.run()
        removal_test_results[edge_key] = result
```

**Justificación del umbral 0.9**:
- Si se pierden >10% de vehículos, la arista es crítica para conectividad
- No es candidata para remoción (causaría desconexión)

**Fase 3: Prueba de Adición (Muestreo)**

```python
# Encontrar pares de nodos cercanos
candidate_edges = get_candidate_addition_edges(
    G, 
    current_nodes_gdf, 
    max_candidates=100,
    max_distance_m=400
)

for (u, v) in candidate_edges:
    # Copiar grafo
    G_mod = G.copy()
    
    # Agregar arista bidireccional
    length = great_circle_distance(u, v)
    G_mod.add_edge(u, v, length=length, speed_kmh=50, ...)
    G_mod.add_edge(v, u, length=length, speed_kmh=50, ...)
    
    # Simular
    result = Microsimulator(G_mod, od_pairs).run()
    addition_test_results[(u,v)] = result
```

**Algoritmo de candidatos**:

```python
def get_candidate_addition_edges(G, nodes_gdf, max_candidates, max_distance_m):
    # 1. Construir KD-Tree para búsqueda espacial eficiente
    points = nodes_gdf[['x', 'y']].values
    tree = cKDTree(points)
    
    # 2. Encontrar pares dentro de distancia máxima
    # Convertir metros a grados (aproximado)
    max_distance_deg = max_distance_m / 111139.0
    candidate_indices = tree.query_pairs(max_distance_deg, p=2)
    
    # 3. Filtrar pares ya conectados
    candidate_edges = []
    for idx_i, idx_j in candidate_indices:
        u = nodes_gdf.index[idx_i]
        v = nodes_gdf.index[idx_j]
        
        if not G.has_edge(u, v) and not G.has_edge(v, u):
            candidate_edges.append((u, v))
    
    # 4. Muestrear aleatoriamente si hay muchos
    if len(candidate_edges) > max_candidates:
        candidate_edges = random.sample(candidate_edges, max_candidates)
    
    return candidate_edges
```

**Fase 4: Generación de Recomendaciones**

```python
def generate_recommendations(base_results, test_results, action_type):
    for key, mod_result in test_results.items():
        # Calcular mejora para cada métrica
        improvements = []
        for metric in ['total_travel_time', 'avg_travel_time', 'vmt', 'completed_trips']:
            base_val = base_results[metric]
            mod_val = mod_result[metric]
            
            # Fórmula: (modificado / base) * 100
            ratio_pct = (mod_val / base_val) * 100
            
            # Para métricas de costo (menor es mejor)
            if metric != 'completed_trips':
                improvement_pct = 100.0 - ratio_pct
            # Para viajes completados (mayor es mejor)
            else:
                improvement_pct = ratio_pct - 100.0
            
            improvements.append(improvement_pct)
        
        # Promedio de mejoras
        avg_improvement = mean(improvements)
        
        # Filtrar por umbral mínimo
        if avg_improvement >= 0.1:
            recommendations.append({
                'osmid': edge_name,
                'action': action_type,
                'impact_pct': avg_improvement,
                'justification': f"{action_type} mejora promedio en un {avg_improvement:.1f}%",
                'geometry': edge_geometry
            })
```

**Fase 5: Normalización y Colores**

```python
# Combinar recomendaciones
local_recommendations = removal_recs + addition_recs

# Ordenar por impacto
local_recommendations.sort(key=lambda x: x['impact_pct'], reverse=True)

# Normalización min-max
impacts = [r['impact_pct'] for r in local_recommendations]
min_impact = min(impacts)
max_impact = max(impacts)

for rec in local_recommendations:
    # Normalizar
    normalized = (rec['impact_pct'] - min_impact) / (max_impact - min_impact)
    rec['normalized_score'] = normalized
    
    # Categorizar
    if normalized < 0.333:
        rec['color_category'] = 'low'
    elif normalized < 0.666:
        rec['color_category'] = 'medium'
    else:
        rec['color_category'] = 'high'
    
    # Asignar color
    if rec['action'] == 'remove':
        colors = {'high': '#e53e3e', 'medium': '#f97316', 'low': '#3b82f6'}
    else:
        colors = {'high': '#38a169', 'medium': '#eab308', 'low': '#a855f7'}
    
    rec['color'] = colors[rec['color_category']]
```

#### Sección 7: Endpoints Flask (Líneas 706-860)

**`POST /api/simulate`**:

```python
@app.route('/api/simulate', methods=['POST'])
def simulate():
    # 1. Recibir ubicación
    place = request.json.get('place')
    
    # 2. Descargar red de OSM
    G = ox.graph_from_place(place, network_type='drive')
    G = prepare_osm_graph(G)
    
    # 3. Convertir a GeoDataFrames
    current_nodes_gdf, current_edges_gdf = ox.graph_to_gdfs(G)
    
    # 4. Ejecutar simulación completa
    sim_results, recommendations, _ = run_simulation(G)
    
    # 5. Retornar resultados
    return jsonify({
        'success': True,
        'results': sim_results,
        'recommendations': recommendations,
        'edges': edges_json
    })
```

### 2. app.js (393 líneas)

#### Variables Globales (Líneas 1-6)

```javascript
let map = null;                    // Instancia de Leaflet
let simulationRunning = false;     // Flag de simulación activa
let socket = null;                 // Conexión WebSocket
let recommendationLayers = null;   // Capa de recomendaciones
let currentBounds = null;          // Límites del mapa
```

#### Inicialización (Líneas 9-23)

```javascript
document.addEventListener('DOMContentLoaded', function () {
    initMap();              // Crear mapa Leaflet
    setupEventListeners();  // Vincular botones
    connectWebSocket();     // Conectar a servidor
});

function initMap() {
    // Crear mapa centrado en NYC
    map = L.map('map').setView([40.7128, -74.0060], 12);
    
    // Agregar capa de tiles de OSM
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors'
    }).addTo(map);
    
    // Crear capa para recomendaciones
    recommendationLayers = L.layerGroup().addTo(map);
}
```

#### WebSocket (Líneas 51-56)

```javascript
function connectWebSocket() {
    socket = io();  // Socket.IO client
    
    // Escuchar actualizaciones
    socket.on('simulation_update', data => {
        updateProgress(data);
    });
}
```

**Formato de mensajes**:
```javascript
{
    step: 150,
    total_steps: 600,
    status: "Simulación base: paso 150/600",
    active_vehicles: 450,
    completed_trips: 120
}
```

#### Ejecución de Simulación (Líneas 108-172)

```javascript
function runSimulation() {
    // 1. Validar entrada
    const place = document.getElementById('place-input').value;
    if (!place) {
        showStatus("Error: Por favor ingrese una Ciudad/Área.");
        return;
    }
    
    // 2. Configurar UI
    simulationRunning = true;
    btn.disabled = true;
    btn.textContent = 'Descargando...';
    
    // 3. Enviar solicitud
    fetch('/api/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ place: place })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // 4. Mostrar resultados
            displayNetwork(data.edges);
            displayMetrics(data.results);
            displayRecommendations(data.recommendations);
            displayRecommendationsOnMap(data.recommendations);
        }
    });
}
```

#### Visualización de Recomendaciones (Líneas 260-300)

```javascript
function displayRecommendationsOnMap(recommendations) {
    // Limpiar capa
    recommendationLayers.clearLayers();
    
    let boundsGroup = L.featureGroup();
    
    recommendations.forEach(rec => {
        if (rec.geometry && rec.geometry.length > 0) {
            // Usar color del backend
            let color = rec.color || '#808080';
            
            // Convertir coordenadas [lon, lat] a [lat, lon]
            const latLons = rec.geometry.map(coord => [coord[1], coord[0]]);
            
            // Crear polyline
            const polyline = L.polyline(latLons, {
                color: color,
                weight: 6,
                opacity: 0.9,
                dashArray: (rec.action === 'add') ? '10, 10' : null
            });
            
            // Agregar popup
            polyline.bindPopup(`
                <b>Acción: ${rec.action === 'remove' ? 'Remover' : 'Añadir'}</b><br>
                ID: ${rec.osmid}<br>
                Impacto: ${rec.impact_pct.toFixed(1)}%<br>
                Justificación: ${rec.justification}
            `);
            
            // Agregar a mapa
            recommendationLayers.addLayer(polyline);
            boundsGroup.addLayer(polyline);
        }
    });
    
    // Ajustar zoom
    if (boundsGroup.getBounds().isValid()) {
        map.fitBounds(boundsGroup.getBounds().pad(0.1));
    }
}
```

### 3. index.html (115 líneas)

**Estructura semántica**:

```html
<!DOCTYPE html>
<html lang="es">
<head>
    <!-- Metadatos -->
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <!-- Título -->
    <title>Detector de Paradoja de Braess</title>
    
    <!-- CSS -->
    <link rel="stylesheet" href="styles.css">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
    
    <!-- JavaScript -->
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.js"></script>
</head>

<body>
    <div class="container">
        <!-- Encabezado -->
        <header>
            <h1>Detector de Paradoja de Braess y Optimizador de Red Vial</h1>
            <p>Ingrese una ubicación, configure parámetros y ejecute la simulación</p>
        </header>
        
        <!-- Contenido principal -->
        <div class="main-content">
            <!-- Panel izquierdo: Controles -->
            <div class="controls-panel">
                <div class="control-group">
                    <h3>Configuración</h3>
                    <input id="place-input" value="Medellín, Colombia">
                </div>
                
                <div class="control-group">
                    <h3>Control de Simulación</h3>
                    <button id="simulate-btn">Ejecutar Simulación</button>
                </div>
                
                <div class="status-panel">
                    <div id="status-message">Listo para ejecutar simulación</div>
                    <div class="progress-bar">
                        <div id="progress-fill"></div>
                    </div>
                </div>
                
                <div class="export-section">
                    <h3>Exportar Resultados</h3>
                    <button id="export-geojson">Exportar GeoJSON</button>
                    <button id="export-csv">Exportar CSV</button>
                    <button id="export-modified-graph">Exportar Red Modificada</button>
                </div>
            </div>
            
            <!-- Panel central: Mapa -->
            <div class="map-container">
                <div id="map"></div>
            </div>
            
            <!-- Panel derecho: Resultados -->
            <div class="results-panel">
                <div class="metrics-panel">
                    <h3>Métricas de Simulación</h3>
                    <div id="metrics-content"></div>
                </div>
                
                <div class="recommendations-panel">
                    <h3>Top 3 Recomendaciones (En Mapa)</h3>
                    <div id="top5-recommendations-content"></div>
                </div>
                
                <div class="recommendations-panel">
                    <h3>Otras Recomendaciones</h3>
                    <div id="all-recommendations-content"></div>
                    <button id="show-more-btn">Ver más</button>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Script principal -->
    <script src="app.js"></script>
</body>
</html>
```

### 4. styles.css (286 líneas)

**Sistema de diseño**:

```css
/* Reset */
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

/* Tipografía */
body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    line-height: 1.6;
}

/* Layout principal con Grid */
.main-content {
    display: grid;
    grid-template-columns: 300px 1fr 400px;
    gap: 20px;
    height: calc(100vh - 200px);
}

/* Responsivo */
@media (max-width: 1200px) {
    .main-content {
        grid-template-columns: 1fr 400px;
    }
}

@media (max-width: 768px) {
    .main-content {
        grid-template-columns: 1fr;
    }
}
```

**Paleta de colores**:

```css
/* Colores principales */
--primary: #667eea;      /* Morado */
--primary-dark: #5a67d8;
--success: #38a169;      /* Verde */
--danger: #e53e3e;       /* Rojo */
--warning: #f97316;      /* Naranja */
--info: #3182ce;         /* Azul */

/* Grises */
--gray-50: #f8fafc;
--gray-100: #f5f7fa;
--gray-200: #e2e8f0;
--gray-600: #4a5568;
--gray-700: #2d3748;
```

---

## 🔄 Flujo de Datos Completo

### Diagrama de Secuencia

```
Usuario          Frontend         Backend          OSMnx           Simulador
  |                |                |                |                |
  |--Ingresa "Medellín"------------>|                |                |
  |                |                |                |                |
  |                |--POST /api/simulate------------>|                |
  |                |                |                |                |
  |                |                |--graph_from_place("Medellín")-->|
  |                |                |                |                |
  |                |                |<--Grafo de NetworkX-------------|
  |                |                |                |                |
  |                |                |--prepare_osm_graph()----------->|
  |                |                |                |                |
  |                |                |--create_demand_matrix()-------->|
  |                |                |                |                |
  |                |                |--Microsimulator(G, od_pairs)--->|
  |                |                |                |                |
  |                |                |                |                |--run()
  |                |                |                |                |
  |                |<--WebSocket: "Simulación base: 50/600"-----------|
  |<--Actualizar barra de progreso--|                |                |
  |                |                |                |                |
  |                |                |                |                |<--base_results
  |                |                |                |                |
  |                |                |--Para cada arista:              |
  |                |                |  G_mod = G.copy()               |
  |                |                |  G_mod.remove_edge(e)           |
  |                |                |  Microsimulator(G_mod).run()-->|
  |                |                |                |                |
  |                |<--WebSocket: "Probando remoción: 100/350"--------|
  |<--Actualizar progreso-----------|                |                |
  |                |                |                |                |
  |                |                |--generate_recommendations()---->|
  |                |                |                |                |
  |                |                |--normalize_and_assign_colors()->|
  |                |                |                |                |
  |                |<--JSON: {success, results, recommendations}------|
  |                |                |                |                |
  |<--Mostrar mapa y resultados-----|                |                |
  |                |                |                |                |
```

---

## 📐 Métricas y Cálculos

### Cálculo de Mejora

**Fórmula general**:

```
Para métricas de costo (TTT, ATT, VMT):
  Mejora (%) = (1 - Valor_modificado / Valor_base) × 100

Para métricas de beneficio (Completed Trips):
  Mejora (%) = (Valor_modificado / Valor_base - 1) × 100
```

**Ejemplo**:

```
Base:
  TTT = 50,000 s
  ATT = 250 s
  VMT = 100,000 m
  Trips = 200

Modificado (removiendo arista X):
  TTT = 45,000 s
  ATT = 225 s
  VMT = 95,000 m
  Trips = 200

Mejoras:
  TTT: (1 - 45000/50000) × 100 = 10%
  ATT: (1 - 225/250) × 100 = 10%
  VMT: (1 - 95000/100000) × 100 = 5%
  Trips: (200/200 - 1) × 100 = 0%

Mejora promedio: (10 + 10 + 5 + 0) / 4 = 6.25%
```

### Normalización Min-Max

**Fórmula**:

```
Score_normalizado = (x - min(X)) / (max(X) - min(X))

Donde:
  x = mejora de la recomendación i
  X = conjunto de todas las mejoras
```

**Ejemplo**:

```
Mejoras: [2%, 5%, 8%, 12%, 15%, 20%]

min(X) = 2%
max(X) = 20%

Scores normalizados:
  2%:  (2-2)/(20-2)   = 0.000 → Bajo
  5%:  (5-2)/(20-2)   = 0.167 → Bajo
  8%:  (8-2)/(20-2)   = 0.333 → Medio
  12%: (12-2)/(20-2)  = 0.556 → Medio
  15%: (15-2)/(20-2)  = 0.722 → Alto
  20%: (20-2)/(20-2)  = 1.000 → Alto
```

### Complejidad Computacional

**Simulación base**: O(V × T)
- V = número de vehículos
- T = número de pasos temporales

**Prueba de remoción**: O(E × V × T)
- E = número de aristas

**Prueba de adición**: O(C × V × T)
- C = número de candidatos (≤ 100)

**Total**: O((E + C) × V × T)

**Ejemplo**:
```
Red de 500 aristas, 100 candidatos
3000 vehículos, 600 pasos

Simulaciones totales: 1 + 500 + 100 = 601
Tiempo estimado: 601 × 10s = 6010s ≈ 100 minutos
```

---

## 🎯 Conclusiones

Este sistema implementa un análisis exhaustivo de redes viales para detectar paradojas de Braess mediante:

1. **Simulación microscópica realista** con modelo IDM
2. **Análisis de fuerza bruta** para remociones
3. **Muestreo inteligente** para adiciones
4. **Visualización intuitiva** con colores normalizados
5. **Exportación flexible** en múltiples formatos

La combinación de estos elementos permite identificar oportunidades contraintuitivas de mejora en redes de tráfico reales.

---

**Documento generado**: Enero 2026  
**Versión del sistema**: 2.0  
**Autor**: Sistema de Detección de Paradoja de Braess
