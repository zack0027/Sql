using System;
using UnityEngine;

namespace JCain.WMS.Models
{
    /// <summary>
    /// Mensaje genérico que llega por WebSocket (contrato v2). El backend manda 3 tipos:
    /// "hello" al conectar, "anomaly" cuando hay anomalía, "narration" cuando el
    /// generador de texto termina de procesar. Esta clase mapea el superset de campos
    /// aplanados de ambos tipos.
    /// </summary>
    [Serializable]
    public class WMSMessage
    {
        public string type;

        // Campos de "anomaly"
        public string id;
        public string movement_id;
        public string rack_id;
        public string anomaly_type;
        public string severity;
        public string detail;
        public string detector;
        public string timestamp;

        // Campos de "narration"
        public string anomaly_id;
        public string text;
        public string likely_cause;
        public string recommended_action;
        public string model;
        public int latency_ms;
        public string emitted_at;

        public bool IsAnomaly => type == "anomaly";
        public bool IsNarration => type == "narration";
        public bool IsHello => type == "hello";
    }

    /// <summary>
    /// Sonda mínima para identificar el tipo de mensaje sin parsear todo el payload.
    /// Útil cuando queremos dispatchear según el campo `type` antes del deserializado completo.
    /// </summary>
    [Serializable]
    public class MessageTypeProbe
    {
        public string type;
    }

    /// <summary>
    /// Niveles de severidad del contrato v2. El string del backend
    /// ("LOW" / "MEDIUM" / "HIGH") se parsea con SeverityHelper.Parse.
    /// </summary>
    public enum Severity
    {
        Low = 0,
        Medium = 1,
        High = 2
    }

    public static class SeverityHelper
    {
        public static Severity Parse(string raw)
        {
            if (string.IsNullOrEmpty(raw)) return Severity.Low;
            switch (raw.Trim().ToLowerInvariant())
            {
                case "high":     return Severity.High;
                case "medium":   return Severity.Medium;
                case "low":      return Severity.Low;
                default:         return Severity.Low;
            }
        }

        /// <summary>
        /// Color base para cada nivel. Usado por AnomalyVisualizer.
        /// Valores en HDR para que el bloom del URP los amplifique.
        /// </summary>
        public static Color ToColor(Severity s)
        {
            switch (s)
            {
                case Severity.High:   return new Color(2.5f, 0.1f, 0.1f); // rojo HDR
                case Severity.Medium: return new Color(2.0f, 0.8f, 0.0f); // ámbar
                case Severity.Low:    return new Color(0.5f, 0.5f, 1.5f); // azul
                default:              return new Color(0.5f, 0.5f, 1.5f); // azul
            }
        }

        /// <summary>Duración del pulso visual en segundos según severidad.</summary>
        public static float PulseDuration(Severity s)
        {
            switch (s)
            {
                case Severity.High:   return 4f;
                case Severity.Medium: return 2.5f;
                case Severity.Low:    return 1f;
                default:              return 1f;
            }
        }
    }
}
