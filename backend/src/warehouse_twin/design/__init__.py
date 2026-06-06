"""Fase de diseño OFFLINE (v2, §6).

Aquí el LLM (Ollama local) trabaja sin prisa produciendo artefactos
versionados que el runtime consume: reglas destiladas, plantillas de
narración y reportes de evaluación. NADA de esto corre en el camino
crítico del runtime.

Módulos:
  - rule_distiller    : destila reglas a partir de los falsos negativos
  - template_generator: genera variantes de narración por tipo de anomalía
  - evaluate          : precisión / recall / F1 por tipo sobre ground truth
"""
