using System;
using UnityEngine;

namespace JCain.WMS.Models
{
    /// <summary>
    /// Mensaje genérico que llega por WebSocket. El backend manda 3 tipos:
    /// "hello" al conectar, "alert" cuando hay anomalía, "narrative" cuando el LLM
    /// termina de procesar. Esta clase mapea el superset de campos.
    /// </summary>
    [Serializable]
    public class WMSMessage
    {
        public string type;

        // Campos de "alert"
        public string movement_id;
        public string timestamp;
        public string movement_type;
        public string sku;
        public string location;
        public string user_id;
        public int quantity;
        public int duration_sec;
        public string severity;
        public bool is_anomaly;
        public string rule_reasons;

        // Campos de "narrative"
        public string narrative;
        public string likely_cause;
        public string recommended_action;
        public string source;
        public string model;
        public float latency_sec;
        public string emitted_at;

        public bool IsAlert => type == "alert";
        public bool IsNarrative => type == "narrative";
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
    /// Niveles de severidad. El string del backend ("low" / "medium" / "high" / "critical")
    /// se parsea con SeverityHelper.Parse.
    /// </summary>
    public enum Severity
    {
        Normal = 0,
        Medium = 1,
        High = 2,
        Critical = 3
    }

    public static class SeverityHelper
    {
        public static Severity Parse(string raw)
        {
            if (string.IsNullOrEmpty(raw)) return Severity.Normal;
            switch (raw.Trim().ToLowerInvariant())
            {
                case "critical": return Severity.Critical;
                case "high":     return Severity.High;
                case "medium":   return Severity.Medium;
                default:         return Severity.Normal;
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
                case Severity.Critical: return new Color(2.5f, 0.1f, 0.1f); // rojo intenso
                case Severity.High:     return new Color(2.0f, 0.6f, 0.0f); // ámbar
                case Severity.Medium:   return new Color(1.2f, 1.2f, 0.2f); // amarillo
                default:                return new Color(0.4f, 0.4f, 0.4f); // gris
            }
        }

        /// <summary>Duración del pulso visual en segundos según severidad.</summary>
        public static float PulseDuration(Severity s)
        {
            switch (s)
            {
                case Severity.Critical: return 6f;
                case Severity.High:     return 4f;
                case Severity.Medium:   return 2.5f;
                default:                return 1f;
            }
        }
    }
}
