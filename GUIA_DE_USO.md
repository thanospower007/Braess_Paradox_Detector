# 📚 Guía Completa del Detector de Paradoja de Braess

## 📋 Tabla de Contenidos
1. [Introducción](#introducción)[cite: 10]
2. [Acceso al Sistema en la Nube](#acceso-al-sistema-en-la-nube)
3. [Ubicaciones Recomendadas para Pruebas Rápidas](#ubicaciones-recomendadas-para-pruebas-rápidas)[cite: 10]
4. [Guía de Uso de la Interfaz](#guía-de-uso-de-la-interfaz)[cite: 10]
5. [Interpretación de Resultados](#interpretación-de-resultados)[cite: 10]
6. [Arquitectura del Sistema](#arquitectura-del-sistema)[cite: 10]
7. [Explicación Técnica Detallada](#explicación-técnica-detallada)[cite: 10]
8. [Mantenimiento y Hosting (Render + GitHub)](#mantenimiento-y-hosting-render--github)

---

## 🎯 Introducción

### ¿Qué es la Paradoja de Braess?

La **Paradoja de Braess** es un fenómeno contraintuitivo en teoría de redes donde **agregar capacidad adicional a una red puede empeorar el rendimiento general**. En el contexto del tráfico vehicular:

- **Caso típico**: Se construye una nueva carretera para aliviar la congestión
- **Resultado paradójico**: El tiempo de viaje promedio aumenta para todos[cite: 10]
- **Razón**: Los conductores egoístas optimizan sus rutas individuales, creando un equilibrio de Nash subóptimo[cite: 10]

### ¿Qué hace este sistema?[cite: 10]

Este sistema es un **simulador de tráfico microscópico** que:[cite: 10]

1. **Descarga** redes viales reales de OpenStreetMap[cite: 10]
2. **Simula** el comportamiento de vehículos individuales usando el modelo IDM (Intelligent Driver Model)[cite: 10]
3. **Analiza** todas las aristas (calles) de la red para detectar paradojas de Braess[cite: 10]
4. **Recomienda** qué calles remover o agregar para mejorar el flujo de tráfico[cite: 10]
5. **Visualiza** las recomendaciones en un mapa interactivo con colores según su impacto[cite: 10]

---

## 🌐 Acceso al Sistema en la Nube

El sistema se encuentra alojado públicamente y no requiere instalación local de Python, librerías ni dependencias.

### URL de Acceso
**Enlace:** `https://braess-simulator.onrender.com`

### Requisitos de Uso
- **Navegador web moderno** (Chrome, Firefox, Edge)[cite: 10].
- **Conexión a Internet** (para descargar mapas de OpenStreetMap)[cite: 10].

> **⚠️ Nota de Suspensión (Cold Start):** El sistema utiliza un plan de hosting gratuito en Render. Si el servidor pasa más de 15 minutos sin recibir visitas, entrará en modo de suspensión. Al acceder al enlace después de un tiempo de inactividad, la página puede tardar entre 30 y 50 segundos en cargar mientras el servidor se "despierta". Una vez cargada, funcionará a velocidad normal.

---

## 🗺️ Ubicaciones Recomendadas para Pruebas Rápidas[cite: 10]

Para probar la aplicación de manera rápida y efectiva, se recomiendan **áreas pequeñas con redes viales simples**[cite: 10]. Estas ubicaciones tienen entre 50-200 nodos, lo que permite simulaciones de **1-5 minutos**[cite: 10].

### 🇨🇴 Colombia[cite: 10]
- `"Guatapé, Antioquia, Colombia"` (Simulación: 1-3 minutos)[cite: 10]
- `"Barrio Colombia, Medellín, Colombia"` (Simulación: 1-3 minutos)[cite: 10]
- `"La Candelaria, Bogotá, Colombia"` (Simulación: 1-3 minutos)[cite: 10]
- `"Laureles, Medellín, Colombia"` (Simulación: 3-5 minutos)[cite: 10]

### 🇺🇸 Estados Unidos[cite: 10]
- `"Woodstock, Vermont, USA"` (Simulación: 1-2 minutos)[cite: 10]
- `"SoHo, Manhattan, New York, USA"` (Simulación: 2-4 minutos)[cite: 10]

### 🇪🇸 España[cite: 10]
- `"Ronda, Málaga, España"` (Simulación: 1-3 minutos)[cite: 10]
- `"Barrio Gótico, Barcelona, España"` (Simulación: 2-4 minutos)[cite: 10]

---

## 💻 Guía de Uso de la Interfaz[cite: 10]

### Panel de Controles (Izquierda)[cite: 10]

**Campo: Ciudad/Área**[cite: 10]
- **Qué es**: Nombre de la ubicación a analizar[cite: 10]
- **Formato**: `"Nombre, Ciudad, País"`[cite: 10]
- **Ejemplos válidos**: `"La Candelaria, Medellín, Colombia"`[cite: 10]

**Botón: "Ejecutar Simulación"**[cite: 10]
- **Función**: Inicia el análisis completo[cite: 10]
- **Estados del botón**:[cite: 10]
  - 🔵 **"Descargando..."**: Obteniendo red de OpenStreetMap[cite: 10]
  - 🔵 **"Simulando... (X%)"**: Ejecutando simulación[cite: 10]
  - 🟢 **"¡Simulación completada!"**: Proceso finalizado[cite: 10]

**Exportar Resultados**[cite: 10]
- **Exportar GeoJSON**: Descarga archivo `.geojson` con todas las recomendaciones[cite: 10].
- **Exportar CSV**: Descarga tabla `.csv` con recomendaciones[cite: 10].
- **Exportar Red Modificada**: Descarga archivo `.graphml` con la red optimizada[cite: 10].

### Panel del Mapa (Centro)[cite: 10]

Las recomendaciones se muestran con **colores según su impacto normalizado**:[cite: 10]

**🔴 Recomendaciones de REMOCIÓN:**[cite: 10]
- **Rojo (#e53e3e)**: Alto impacto [66.6% - 100%][cite: 10]
- **Naranja (#f97316)**: Impacto medio [33.3% - 66.6%)[cite: 10]
- **Azul (#3b82f6)**: Bajo impacto [0% - 33.3%)[cite: 10]

**🟢 Recomendaciones de ADICIÓN:**[cite: 10]
- **Verde (#38a169)**: Alto impacto [66.6% - 100%][cite: 10]
- **Amarillo (#eab308)**: Impacto medio [33.3% - 66.6%)[cite: 10]
- **Morado (#a855f7)**: Bajo impacto [0% - 33.3%)[cite: 10]

---

## 📊 Interpretación de Resultados[cite: 10]

### Cómo Leer el Porcentaje de Mejora[cite: 10]

El **porcentaje de mejora** se calcula como:[cite: 10]
