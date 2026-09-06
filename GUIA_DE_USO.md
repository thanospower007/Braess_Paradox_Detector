# 📚 Guía Completa del Detector de Paradoja de Braess

## 📋 Tabla de Contenidos
1. [Introducción](#introducción)
2. [Requisitos del Sistema](#requisitos-del-sistema)
3. [Instalación](#instalación)
4. [Ejecución del Sistema](#ejecución-del-sistema)
5. [Guía de Uso de la Interfaz](#guía-de-uso-de-la-interfaz)
6. [Interpretación de Resultados](#interpretación-de-resultados)
7. [Arquitectura del Sistema](#arquitectura-del-sistema)
8. [Explicación Técnica Detallada](#explicación-técnica-detallada)

---

## 🎯 Introducción

### ¿Qué es la Paradoja de Braess?

La **Paradoja de Braess** es un fenómeno contraintuitivo en teoría de redes donde **agregar capacidad adicional a una red puede empeorar el rendimiento general**. En el contexto del tráfico vehicular:

- **Caso típico**: Se construye una nueva carretera para aliviar la congestión
- **Resultado paradójico**: El tiempo de viaje promedio aumenta para todos
- **Razón**: Los conductores egoístas optimizan sus rutas individuales, creando un equilibrio de Nash subóptimo

### ¿Qué hace este sistema?

Este sistema es un **simulador de tráfico microscópico** que:

1. **Descarga** redes viales reales de OpenStreetMap
2. **Simula** el comportamiento de vehículos individuales usando el modelo IDM (Intelligent Driver Model)
3. **Analiza** todas las aristas (calles) de la red para detectar paradojas de Braess
4. **Recomienda** qué calles remover o agregar para mejorar el flujo de tráfico
5. **Visualiza** las recomendaciones en un mapa interactivo con colores según su impacto

---

## 💻 Requisitos del Sistema

### Software Necesario

- **Python 3.8+** (recomendado 3.11)
- **Navegador web moderno** (Chrome, Firefox, Edge)
- **Conexión a Internet** (para descargar mapas de OpenStreetMap)

### Librerías de Python

```bash
# Librerías principales
numpy>=1.21.0
scipy>=1.7.0
pandas>=1.3.0
geopandas>=0.10.0
networkx>=2.6.0
osmnx>=1.2.0
shapely>=1.8.0

# Framework web
flask>=2.0.0
flask-socketio>=5.1.0

# Opcional: Aceleración GPU
cupy-cuda11x  # Solo si tienes GPU NVIDIA
```

---

## 🚀 Instalación

### Paso 1: Crear entorno virtual (recomendado)

```bash
# Navegar a la carpeta del proyecto
cd "g:\Mi unidad\Programacion\Python\proyectos\paradoja de braess 2"

# Crear entorno virtual
python -m venv venv

# Activar entorno virtual
# En Windows:
venv\Scripts\activate
# En Linux/Mac:
source venv/bin/activate
```

### Paso 2: Instalar dependencias

```bash
# Instalar todas las librerías
pip install numpy scipy pandas geopandas networkx osmnx shapely flask flask-socketio python-socketio eventlet

# Opcional: Para aceleración GPU (requiere NVIDIA GPU)
pip install cupy-cuda11x
```

### Paso 3: Verificar instalación

```bash
python -c "import osmnx; import flask; import networkx; print('✅ Instalación exitosa')"
```

---

## ▶️ Ejecución del Sistema

### Método 1: Ejecución Estándar

```bash
# 1. Abrir terminal en la carpeta del proyecto
cd "g:\Mi unidad\Programacion\Python\proyectos\paradoja de braess 2"

# 2. Activar entorno virtual (si lo creaste)
venv\Scripts\activate

# 3. Ejecutar el servidor backend
python backend.py

# 4. Abrir navegador en:
http://localhost:5000
```

### Método 2: Ejecución con puerto personalizado

```python
# Editar la última línea de backend.py:
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8080, debug=True)
```

### Señales de Ejecución Correcta

Al ejecutar `python backend.py`, deberías ver:

```
INFO:__main__:Usando CuPy para aceleración por GPU. ✅
 * Serving Flask app 'backend'
 * Debug mode: on
WARNING: This is a development server. Do not use it in a production deployment.
 * Running on http://127.0.0.1:5000
```

---

## �️ Ubicaciones Recomendadas para Pruebas Rápidas

Para probar la aplicación de manera rápida y efectiva, se recomiendan **áreas pequeñas con redes viales simples**. Estas ubicaciones tienen entre 50-200 nodos, lo que permite simulaciones de **1-5 minutos**.

### 🇨🇴 Colombia

#### Zonas Pequeñas (Simulación: 1-3 minutos)

**Barrios residenciales:**
- `"Barrio Colombia, Medellín, Colombia"`
- `"Boston, Medellín, Colombia"`
- `"Prado Centro, Medellín, Colombia"`
- `"Chapinero Alto, Bogotá, Colombia"`
- `"San Antonio, Cali, Colombia"`
- `"El Poblado, Envigado, Colombia"`

**Centros históricos:**
- `"Centro Histórico, Cartagena, Colombia"`
- `"La Candelaria, Bogotá, Colombia"`
- `"Parque Caldas, Manizales, Colombia"`

**Municipios pequeños:**
- `"Guatapé, Antioquia, Colombia"`
- `"Jardín, Antioquia, Colombia"`
- `"Salento, Quindío, Colombia"`
- `"Villa de Leyva, Boyacá, Colombia"`

#### Zonas Medianas (Simulación: 3-5 minutos)

- `"Laureles, Medellín, Colombia"`
- `"Usaquén, Bogotá, Colombia"`
- `"Granada, Cali, Colombia"`
- `"Cabecera, Bucaramanga, Colombia"`

### 🇺🇸 Estados Unidos

#### Pueblos pequeños (Simulación: 1-2 minutos)

- `"Woodstock, Vermont, USA"`
- `"Telluride, Colorado, USA"`
- `"Marfa, Texas, USA"`
- `"Sedona, Arizona, USA"`
- `"Key West, Florida, USA"`

#### Barrios urbanos (Simulación: 2-4 minutos)

- `"SoHo, Manhattan, New York, USA"`
- `"North Beach, San Francisco, USA"`
- `"Georgetown, Washington DC, USA"`
- `"French Quarter, New Orleans, USA"`

### 🇪🇸 España

#### Pueblos (Simulación: 1-3 minutos)

- `"Ronda, Málaga, España"`
- `"Cudillero, Asturias, España"`
- `"Albarracín, Teruel, España"`
- `"Frigiliana, Málaga, España"`

#### Barrios históricos (Simulación: 2-4 minutos)

- `"Barrio Gótico, Barcelona, España"`
- `"Albaicín, Granada, España"`
- `"Casco Viejo, Bilbao, España"`
- `"Barrio de Santa Cruz, Sevilla, España"`

### 🇲🇽 México

#### Pueblos mágicos (Simulación: 1-3 minutos)

- `"San Miguel de Allende, Guanajuato, México"`
- `"Taxco, Guerrero, México"`
- `"Valle de Bravo, Estado de México, México"`
- `"Tepoztlán, Morelos, México"`

#### Zonas coloniales (Simulación: 2-4 minutos)

- `"Centro Histórico, Guanajuato, México"`
- `"Zona Rosa, Ciudad de México, México"`
- `"Centro Histórico, Oaxaca, México"`

### 🇦🇷 Argentina

#### Barrios (Simulación: 2-4 minutos)

- `"San Telmo, Buenos Aires, Argentina"`
- `"Palermo Soho, Buenos Aires, Argentina"`
- `"La Boca, Buenos Aires, Argentina"`
- `"Güemes, Córdoba, Argentina"`

### 🇨🇱 Chile

#### Barrios (Simulación: 2-4 minutos)

- `"Bellavista, Santiago, Chile"`
- `"Lastarria, Santiago, Chile"`
- `"Cerro Alegre, Valparaíso, Chile"`

### 🇵🇪 Perú

#### Zonas turísticas (Simulación: 1-3 minutos)

- `"Miraflores, Lima, Perú"`
- `"Barranco, Lima, Perú"`
- `"Centro Histórico, Cusco, Perú"`
- `"Centro Histórico, Arequipa, Perú"`

### 🇪🇨 Ecuador

#### Centros históricos (Simulación: 2-4 minutos)

- `"Centro Histórico, Quito, Ecuador"`
- `"Centro Histórico, Cuenca, Ecuador"`
- `"Las Peñas, Guayaquil, Ecuador"`

### 🌍 Europa (Otros)

#### Pueblos pintorescos (Simulación: 1-3 minutos)

- `"Hallstatt, Austria"`
- `"Giethoorn, Netherlands"`
- `"Rothenburg ob der Tauber, Germany"`
- `"Cinque Terre, Italy"`
- `"Sintra, Portugal"`

### 🏝️ Islas y Zonas Costeras (Simulación: 1-2 minutos)

- `"Bocas del Toro, Panamá"`
- `"Isla Mujeres, México"`
- `"Roatán, Honduras"`
- `"San Andrés, Colombia"`

---

## 💡 Consejos para Elegir Ubicaciones de Prueba

### ✅ Características Ideales

1. **Tamaño**: Barrios de 0.5-2 km²
2. **Nodos**: 50-200 intersecciones
3. **Conectividad**: Red bien conectada pero no demasiado densa
4. **Tipo**: Centros históricos, pueblos pequeños, barrios residenciales

### ❌ Evitar

1. **Ciudades completas**: `"Medellín, Colombia"` (muy grande)
2. **Áreas metropolitanas**: `"Greater London, UK"` (demasiado grande)
3. **Zonas rurales aisladas**: Pocas calles, resultados poco interesantes
4. **Autopistas**: Redes muy simples sin paradojas

### 🎯 Estrategia de Prueba Progresiva

**Nivel 1 - Prueba Inicial (1-2 min)**
```
"Guatapé, Antioquia, Colombia"
```
- Red muy simple (~50 nodos)
- Ideal para verificar instalación
- Resultados en 1-2 minutos

**Nivel 2 - Prueba Intermedia (3-5 min)**
```
"La Candelaria, Bogotá, Colombia"
```
- Red moderada (~150 nodos)
- Muestra capacidades del sistema
- Resultados en 3-5 minutos

**Nivel 3 - Análisis Completo (10-20 min)**
```
"Laureles, Medellín, Colombia"
```
- Red compleja (~300 nodos)
- Análisis detallado
- Resultados en 10-20 minutos

---

## �🖥️ Guía de Uso de la Interfaz


### Pantalla Principal

La interfaz está dividida en **3 paneles**:

```
┌─────────────────────────────────────────────────────────────┐
│              DETECTOR DE PARADOJA DE BRAESS                 │
├──────────────┬──────────────────────────┬───────────────────┤
│              │                          │                   │
│  CONTROLES   │         MAPA             │    RESULTADOS     │
│  (Izquierda) │       (Centro)           │    (Derecha)      │
│              │                          │                   │
└──────────────┴──────────────────────────┴───────────────────┘
```

### Panel de Controles (Izquierda)

#### 1. **Configuración**

**Campo: Ciudad/Área**
- **Qué es**: Nombre de la ubicación a analizar
- **Formato**: `"Nombre, Ciudad, País"`
- **Ejemplos válidos**:
  - `"La Candelaria, Medellín, Colombia"`
  - `"Manhattan, New York, USA"`
  - `"Centro Histórico, Ciudad de México, México"`
  - `"Poblado, Medellín, Colombia"`
- **Consejos**:
  - ✅ Usa nombres específicos de barrios para áreas pequeñas
  - ✅ Incluye ciudad y país para evitar ambigüedades
  - ❌ Evita áreas muy grandes (ciudades completas) - la simulación será muy lenta

#### 2. **Control de Simulación**

**Botón: "Ejecutar Simulación"**
- **Función**: Inicia el análisis completo
- **Estados del botón**:
  - 🔵 **"Descargando..."**: Obteniendo red de OpenStreetMap
  - 🔵 **"Simulando... (X%)"**: Ejecutando simulación
  - 🟢 **"¡Simulación completada!"**: Proceso finalizado
  - ⚪ **"Ejecutar Simulación"**: Listo para nueva simulación

**Barra de Progreso**
- **Verde**: Simulación en progreso
- **Azul**: Pruebas de remoción/adición
- **Muestra**: Paso actual / Total de pasos

**Mensaje de Estado**
- Indica la operación actual:
  - `"Descargando red de [ubicación]..."`
  - `"Simulación base: paso X/Y"`
  - `"Probando remoción de aristas: X/Y"`
  - `"Probando adición de aristas: X/Y"`

#### 3. **Exportar Resultados**

**Botón: "Exportar GeoJSON"**
- **Qué hace**: Descarga archivo `.geojson` con todas las recomendaciones
- **Uso**: Importar en QGIS, ArcGIS, Google Earth, etc.
- **Contenido**: Geometría de calles + metadatos (acción, impacto, justificación)

**Botón: "Exportar CSV"**
- **Qué hace**: Descarga tabla `.csv` con recomendaciones
- **Uso**: Análisis en Excel, Python, R
- **Columnas**: `osmid`, `action`, `impact_pct`, `justification`

**Botón: "Exportar Red Modificada"**
- **Qué hace**: Descarga archivo `.graphml` con la red optimizada
- **Uso**: Análisis avanzado en NetworkX, Gephi
- **Contenido**: Grafo completo con todas las recomendaciones aplicadas

### Panel del Mapa (Centro)

#### Elementos Visuales

**Líneas en el Mapa**

Las recomendaciones se muestran con **colores según su impacto normalizado**:

**🔴 Recomendaciones de REMOCIÓN:**
- **Rojo (#e53e3e)**: Alto impacto [66.6% - 100%]
  - Estas calles causan mucha congestión
  - Removerlas mejorará significativamente el tráfico
  
- **Naranja (#f97316)**: Impacto medio [33.3% - 66.6%)
  - Efecto moderado en el flujo
  - Considerar según prioridades
  
- **Azul (#3b82f6)**: Bajo impacto [0% - 33.3%)
  - Mejora marginal
  - Baja prioridad

**🟢 Recomendaciones de ADICIÓN:**
- **Verde (#38a169)**: Alto impacto [66.6% - 100%]
  - Nuevas conexiones muy beneficiosas
  - Alta prioridad de construcción
  
- **Amarillo (#eab308)**: Impacto medio [33.3% - 66.6%)
  - Mejora moderada
  - Evaluar costo-beneficio
  
- **Morado (#a855f7)**: Bajo impacto [0% - 33.3%)
  - Beneficio marginal
  - Baja prioridad

**Estilo de Líneas:**
- **Línea sólida**: Calle existente (recomendación de remoción)
- **Línea punteada**: Calle nueva (recomendación de adición)

#### Interacción con el Mapa

**Click en una línea**
- Muestra popup con:
  - **Acción**: Remover o Añadir
  - **ID**: Nombre de la calle o coordenadas
  - **Impacto**: Porcentaje de mejora
  - **Justificación**: Explicación técnica

**Controles del Mapa**
- **+/-**: Zoom in/out
- **Arrastrar**: Mover mapa
- **Scroll**: Zoom con rueda del mouse

### Panel de Resultados (Derecha)

#### 1. **Métricas de Simulación**

**Tiempo Total de Simulación**
- **Qué es**: Duración del análisis completo
- **Formato**: Segundos (s) o minutos (min)
- **Ejemplo**: `"45.3 s"` o `"2.1 min"`

**Tiempo Promedio de Viaje Base**
- **Qué es**: Tiempo promedio que tarda un vehículo en completar su ruta
- **Unidad**: Segundos
- **Interpretación**: Menor es mejor
- **Ejemplo**: `"234.5 s"` = 3 minutos 54 segundos

**Cambios Estudiados**
- **Qué es**: Total de modificaciones probadas (remociones + adiciones)
- **Ejemplo**: `"450"` = Se probaron 450 cambios diferentes

**Cambios con Mejora**
- **Qué es**: Cuántos cambios mejoraron el tráfico
- **Interpretación**: Mayor número = más oportunidades de optimización

**% Cambios con Mejora**
- **Qué es**: Porcentaje de cambios que mejoraron el sistema
- **Interpretación**:
  - `> 10%`: Red con muchas oportunidades de mejora
  - `5-10%`: Oportunidades moderadas
  - `< 5%`: Red relativamente optimizada

**Total de Recomendaciones**
- **Qué es**: Número de cambios recomendados (filtrados por umbral de mejora)
- **Nota**: Solo se muestran cambios con mejora ≥ 0.1%

#### 2. **Top 3 Recomendaciones (En Mapa)**

Muestra las **3 recomendaciones más impactantes** que están visualizadas en el mapa.

**Formato de cada recomendación:**

```
┌─────────────────────────────────────────────────┐
│ Calle 80 (Autopista)              +12.5% ✅     │
│ Remove mejora promedio en un 12.5%.             │
└─────────────────────────────────────────────────┘
```

**Elementos:**
- **Nombre de la calle**: Identificador legible
- **Porcentaje**: Mejora esperada (verde si positivo)
- **Justificación**: Explicación de la mejora
- **Color de borde**:
  - Rojo: Remoción
  - Verde: Adición

#### 3. **Otras Recomendaciones**

Muestra las siguientes 3 recomendaciones (posiciones 4-6).

**Botón: "Ver más"**
- Expande para mostrar todas las recomendaciones restantes
- Cambia a "Ver menos" para colapsar

---

## 📊 Interpretación de Resultados

### Cómo Leer el Porcentaje de Mejora

El **porcentaje de mejora** se calcula como:

```
Mejora (%) = Promedio de:
  - (1 - Tiempo_modificado / Tiempo_base) × 100%  [para tiempo de viaje]
  - (1 - VMT_modificado / VMT_base) × 100%        [para distancia recorrida]
  - (Viajes_modificado / Viajes_base - 1) × 100%  [para viajes completados]
```

**Interpretación:**
- **+15%**: Mejora excelente - Alta prioridad
- **+5% a +15%**: Mejora significativa - Considerar implementación
- **+1% a +5%**: Mejora moderada - Evaluar costo-beneficio
- **+0.1% a +1%**: Mejora marginal - Baja prioridad

### Normalización de Colores

Los colores se asignan usando **normalización min-max**:

```
Score normalizado = (Mejora_i - Mejora_mín) / (Mejora_máx - Mejora_mín)

Categorías:
- Bajo:   [0.000, 0.333)
- Medio:  [0.333, 0.666)
- Alto:   [0.666, 1.000]
```

**Ejemplo:**
- Si las mejoras van de 2% a 20%:
  - 2% → Score = 0.00 → Bajo (azul/morado)
  - 11% → Score = 0.50 → Medio (naranja/amarillo)
  - 20% → Score = 1.00 → Alto (rojo/verde)

### Casos de Uso Prácticos

#### Caso 1: Planificación Urbana

**Escenario**: Autoridad de tránsito quiere reducir congestión

**Pasos:**
1. Ejecutar simulación en zona congestionada
2. Identificar calles rojas (alto impacto de remoción)
3. Evaluar si son candidatas para:
   - Peatonalización
   - Ciclovías
   - Transporte público exclusivo
4. Identificar calles verdes (alto impacto de adición)
5. Priorizar construcción de nuevas vías

#### Caso 2: Investigación Académica

**Escenario**: Estudiar paradoja de Braess en ciudad real

**Pasos:**
1. Ejecutar simulación en múltiples barrios
2. Exportar resultados a CSV
3. Analizar correlaciones:
   - Tipo de vía vs. probabilidad de paradoja
   - Densidad de red vs. número de recomendaciones
4. Exportar red modificada para análisis en NetworkX

#### Caso 3: Evaluación de Impacto

**Escenario**: Evaluar si una nueva calle mejorará el tráfico

**Pasos:**
1. Ejecutar simulación en estado actual
2. Buscar en recomendaciones de adición (líneas punteadas)
3. Si la calle propuesta aparece en verde → Beneficiosa
4. Si no aparece → Evaluar manualmente o cambiar parámetros

---

## 🏗️ Arquitectura del Sistema

### Diagrama de Componentes

```
┌─────────────────────────────────────────────────────────────┐
│                        USUARIO                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   FRONTEND (Navegador)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  index.html  │  │   app.js     │  │  styles.css  │     │
│  │  (Estructura)│  │  (Lógica)    │  │  (Estilos)   │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP/WebSocket
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   BACKEND (Python)                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                    backend.py                        │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐    │  │
│  │  │   Flask    │  │  OSMnx     │  │ Simulador  │    │  │
│  │  │ (Servidor) │  │ (Mapas)    │  │ (Tráfico)  │    │  │
│  │  └────────────┘  └────────────┘  └────────────┘    │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  SERVICIOS EXTERNOS                         │
│  ┌──────────────┐  ┌──────────────┐                        │
│  │ OpenStreetMap│  │   Leaflet    │                        │
│  │  (Datos)     │  │   (Mapas)    │                        │
│  └──────────────┘  └──────────────┘                        │
└─────────────────────────────────────────────────────────────┘
```

### Flujo de Datos

```
1. Usuario ingresa ubicación
   ↓
2. Frontend envía solicitud POST a /api/simulate
   ↓
3. Backend descarga red de OpenStreetMap
   ↓
4. Backend ejecuta simulación base
   ↓
5. Backend prueba remoción de cada arista
   ↓
6. Backend prueba adición de aristas candidatas
   ↓
7. Backend calcula mejoras y asigna colores
   ↓
8. Backend envía resultados a Frontend
   ↓
9. Frontend muestra mapa y recomendaciones
   ↓
10. Usuario interactúa con resultados
```

---

## 🔬 Explicación Técnica Detallada

### 1. Backend (backend.py)

#### Componentes Principales

**A. Configuración Inicial (Líneas 1-63)**

```python
# Intenta usar CuPy para GPU
try:
    import cupy as cp
    np = cp
    USE_CUPY = True
except ImportError:
    import numpy as np
    USE_CUPY = False
```

**Qué hace**: Detecta si hay GPU disponible para acelerar cálculos
**Por qué**: Las operaciones con arrays son 10-100x más rápidas en GPU

**B. Clase Vehicle (Líneas 102-114)**

Representa un vehículo individual en la simulación.

**Atributos:**
- `id`: Identificador único
- `origin`: Nodo de origen
- `destination`: Nodo de destino
- `route`: Lista de aristas a recorrer
- `current_edge_index`: Posición en la ruta
- `position_on_edge`: Metros recorridos en arista actual
- `speed`: Velocidad actual (m/s)
- `total_time`: Tiempo acumulado de viaje
- `reactive`: Si recalcula ruta según congestión

**C. Clase Microsimulator (Líneas 116-327)**

Motor de simulación de tráfico microscópico.

**Método `__init__`**: Inicializa simulación
- Crea vehículos para cada par origen-destino
- Calcula rutas iniciales usando Dijkstra
- Asigna vehículos a aristas

**Método `calculate_desired_speed`**: Modelo IDM
```python
# Intelligent Driver Model
acceleration = a * (1 - (v/v0)^4 - (s*/s)^2)
```

**Parámetros IDM:**
- `T = 1.5s`: Tiempo de reacción
- `a = 1.0 m/s²`: Aceleración máxima
- `b = 1.5 m/s²`: Desaceleración confortable
- `s0 = 2.0 m`: Distancia mínima

**Método `run`**: Ejecuta simulación
- Loop temporal con paso `dt = 1.0s`
- Actualiza posición de cada vehículo
- Recalcula rutas de vehículos reactivos cada 30 pasos
- Emite progreso vía WebSocket

**D. Función `run_simulation` (Líneas 399-623)**

Orquesta todo el análisis.

**Fase 1: Simulación Base**
```python
sim_base = Microsimulator(G, od_pairs)
base_results = sim_base.run()
```

**Fase 2: Prueba de Remoción (Fuerza Bruta)**
```python
for edge in G.edges():
    G_mod = G.copy()
    G_mod.remove_edge(edge)
    result = Microsimulator(G_mod, od_pairs).run()
    # Calcular mejora
```

**Fase 3: Prueba de Adición (Muestreo)**
```python
candidates = get_candidate_addition_edges(G, max_distance=400m)
for (u, v) in candidates:
    G_mod = G.copy()
    G_mod.add_edge(u, v, ...)
    result = Microsimulator(G_mod, od_pairs).run()
```

**Fase 4: Normalización y Colores**
```python
# Min-max normalization
normalized = (impact - min_impact) / (max_impact - min_impact)

# Categorización
if normalized < 0.333: category = 'low'
elif normalized < 0.666: category = 'medium'
else: category = 'high'

# Asignación de color
if action == 'remove':
    colors = {'high': '#e53e3e', 'medium': '#f97316', 'low': '#3b82f6'}
else:
    colors = {'high': '#38a169', 'medium': '#eab308', 'low': '#a855f7'}
```

**E. Endpoints de Flask**

**`POST /api/simulate`**: Ejecuta simulación
- Recibe: `{place: "Ubicación"}`
- Retorna: `{success, results, recommendations, edges}`

**`GET /api/recommendations`**: Obtiene recomendaciones
- Retorna: Lista de recomendaciones en JSON

**`GET /api/export/geojson`**: Exporta GeoJSON
- Retorna: FeatureCollection con geometrías

**`GET /api/export/csv`**: Exporta CSV
- Retorna: Archivo CSV descargable

**`GET /api/export/modified_graph`**: Exporta grafo
- Retorna: Archivo GraphML

### 2. Frontend (app.js)

#### Funciones Principales

**A. `initMap()` (Líneas 15-23)**

Inicializa mapa Leaflet.

```javascript
map = L.map('map').setView([40.7128, -74.0060], 12);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
```

**B. `connectWebSocket()` (Líneas 51-56)**

Establece conexión WebSocket para actualizaciones en tiempo real.

```javascript
socket = io();
socket.on('simulation_update', data => updateProgress(data));
```

**C. `runSimulation()` (Líneas 108-172)**

Ejecuta simulación completa.

**Flujo:**
1. Validar entrada
2. Enviar POST a `/api/simulate`
3. Mostrar progreso
4. Recibir resultados
5. Actualizar interfaz

**D. `displayRecommendationsOnMap()` (Líneas 260-300)**

Dibuja recomendaciones en el mapa.

```javascript
recommendations.forEach(rec => {
    let color = rec.color || '#808080';  // Color del backend
    
    const polyline = L.polyline(latLons, {
        color: color,
        weight: 6,
        opacity: 0.9,
        dashArray: (rec.action === 'add') ? '10, 10' : null
    });
    
    polyline.bindPopup(`
        <b>Acción: ${rec.action}</b><br>
        Impacto: ${rec.impact_pct.toFixed(1)}%
    `);
});
```

**E. `displayMetrics()` (Líneas 174-196)**

Muestra métricas de simulación.

**F. `displayRecommendations()` (Líneas 198-258)**

Renderiza lista de recomendaciones.

### 3. HTML (index.html)

**Estructura:**

```html
<div class="container">
  <header>Título y descripción</header>
  
  <div class="main-content">
    <!-- Panel izquierdo: Controles -->
    <div class="controls-panel">
      <input id="place-input">
      <button id="simulate-btn">
      <div id="status-message">
      <div id="progress-bar">
    </div>
    
    <!-- Panel central: Mapa -->
    <div class="map-container">
      <div id="map"></div>
    </div>
    
    <!-- Panel derecho: Resultados -->
    <div class="results-panel">
      <div id="metrics-content">
      <div id="top5-recommendations-content">
      <div id="all-recommendations-content">
    </div>
  </div>
</div>
```

### 4. CSS (styles.css)

**Sistema de Grid:**

```css
.main-content {
    display: grid;
    grid-template-columns: 300px 1fr 400px;
    gap: 20px;
}
```

**Diseño Responsivo:**

```css
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

---

## 🐛 Solución de Problemas

### Error: "Failed to download map"

**Causa**: OpenStreetMap no encuentra la ubicación

**Solución**:
- Verifica ortografía
- Usa nombres más específicos: `"La Candelaria, Medellín"` en vez de `"Medellín"`
- Prueba con variaciones: `"Medellin"` vs `"Medellín"`

### Error: "No OD pairs could be created"

**Causa**: Red muy pequeña o desconectada

**Solución**:
- Usa un área más grande
- Verifica que la zona tenga calles conectadas

### Simulación muy lenta

**Causa**: Red muy grande

**Solución**:
- Reduce el área de estudio
- Usa barrios específicos en vez de ciudades completas
- Instala CuPy para aceleración GPU

### WebSocket desconectado

**Causa**: Firewall o proxy

**Solución**:
- Verifica que puerto 5000 esté abierto
- Desactiva temporalmente firewall
- Usa `localhost` en vez de `127.0.0.1`

---

## 📈 Optimización y Mejores Prácticas

### Para Simulaciones Rápidas

1. **Áreas pequeñas**: Barrios de 1-2 km²
2. **Reducir candidatos**: Modificar `max_candidates=50` en línea 473
3. **GPU**: Instalar CuPy si tienes NVIDIA GPU

### Para Resultados Precisos

1. **Áreas completas**: Incluir zonas circundantes
2. **Aumentar duración**: Modificar `DEFAULT_DURATION_MINUTES = 15`
3. **Más vehículos**: Cambiar `od_pairs.extend([(u, v)] * 10)` en línea 94

### Para Análisis Académico

1. **Exportar todo**: Usar los 3 formatos (GeoJSON, CSV, GraphML)
2. **Documentar parámetros**: Anotar configuración usada
3. **Múltiples ejecuciones**: Promediar resultados de 3-5 simulaciones

---

## 📚 Referencias y Recursos

### Teoría

- **Braess, D. (1968)**: "Über ein Paradoxon aus der Verkehrsplanung"
- **Roughgarden, T. (2005)**: "Selfish Routing and the Price of Anarchy"

### Librerías Usadas

- **OSMnx**: https://osmnx.readthedocs.io/
- **NetworkX**: https://networkx.org/
- **Leaflet**: https://leafletjs.com/
- **Flask**: https://flask.palletsprojects.com/

### Modelo de Tráfico

- **IDM**: Treiber, M., & Kesting, A. (2013). "Traffic Flow Dynamics"

---

## 📝 Notas Finales

### Limitaciones del Sistema

1. **Simplificaciones**:
   - No considera semáforos
   - No modela giros
   - Demanda fija (no varía con el tiempo)

2. **Escalabilidad**:
   - Redes >1000 aristas pueden tardar horas
   - Requiere RAM proporcional al número de vehículos

3. **Precisión**:
   - Modelo simplificado de comportamiento
   - No considera transporte público
   - Asume conductores homogéneos

### Trabajo Futuro

- Integración con datos de tráfico real
- Optimización multi-objetivo
- Interfaz para editar red manualmente
- Exportación de reportes PDF

---

**Versión**: 2.0  
**Última actualización**: Enero 2026  
**Autor**: Sistema de Detección de Paradoja de Braess  
**Licencia**: MIT
