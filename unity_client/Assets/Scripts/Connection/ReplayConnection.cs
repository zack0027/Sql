using System;
using System.Collections;
using UnityEngine;
using UnityEngine.Networking;
using JCain.WMS.Models;

namespace JCain.WMS.Connection
{
    /// <summary>
    /// Reproduce un archivo replay.json (cargado desde StreamingAssets) en lugar
    /// de conectarse a un WebSocket real. Dispara LOS MISMOS eventos C# que
    /// WMSConnection (OnAlert, OnNarrative), por lo que el resto del cliente
    /// Unity no necesita saber si está en modo live o replay.
    ///
    /// Razón de existir: GitHub Pages no permite WebSocket sin TLS y el backend
    /// local no es accesible públicamente. Este script hace que la demo funcione
    /// "self-contained" desde un static hosting.
    ///
    /// Diseño del tick: Update() con budget de eventos por frame.
    /// Evita ráfagas visuales cuando un frame se atrasa y acumula varios
    /// eventos vencidos — sin el budget, todos se dispararían en el mismo frame.
    /// </summary>
    [DisallowMultipleComponent]
    public class ReplayConnection : MonoBehaviour
    {
        [Header("Replay file")]
        [Tooltip("Ruta relativa a StreamingAssets/. Ej: replay.json")]
        [SerializeField] private string replayFileName = "replay.json";

        [Header("Playback")]
        [SerializeField] private bool autoStart = true;
        [SerializeField] private bool loop = true;
        [Tooltip("Multiplicador de velocidad. 1.0 = tiempo real, 2.0 = doble velocidad.")]
        [Range(0.25f, 5f)]
        [SerializeField] private float playbackSpeed = 1.0f;
        [Tooltip("Segundos de pausa antes de reiniciar el loop.")]
        [SerializeField] private float loopPauseSec = 2f;
        [Tooltip("Máximo de eventos visuales despachados por frame. Evita ráfagas al recuperarse de lag.")]
        [SerializeField] private int eventsPerFrameBudget = 3;

        [Header("Debug")]
        [SerializeField] private bool logEvents = false;

        // Mismos eventos que WMSConnection: cualquier subscriber no nota la diferencia.
        public static event Action OnConnected;
        public static event Action OnDisconnected;
        public static event Action<WMSMessage> OnAlert;
        public static event Action<WMSMessage> OnNarrative;

        private Replay  _replay;
        private bool    _playing;
        private bool    _loopPausing;
        private int     _nextIndex;
        private float   _startTime;       // Time.time en que arrancó el loop actual
        private float   _resumeTime;      // Time.time en que termina la pausa de loop

        private IEnumerator Start()
        {
            Application.runInBackground = true;
            yield return LoadReplay();
            if (autoStart && _replay != null)
                BeginPlayback();
        }

        /// <summary>
        /// Tick principal. Despacha hasta <eventsPerFrameBudget> eventos por frame,
        /// respetando el timestamp relativo de cada evento escalado por playbackSpeed.
        /// </summary>
        private void Update()
        {
            if (!_playing || _replay == null) return;

            // Loop pause: esperamos antes de reiniciar
            if (_loopPausing)
            {
                if (Time.time >= _resumeTime)
                {
                    _loopPausing = false;
                    ResetPlayhead();
                }
                return;
            }

            float elapsed = (Time.time - _startTime) * Mathf.Max(0.01f, playbackSpeed);
            int budget = eventsPerFrameBudget;

            while (budget > 0 &&
                   _nextIndex < _replay.events.Length &&
                   _replay.events[_nextIndex].t <= elapsed)
            {
                DispatchEvent(_replay.events[_nextIndex].msg);
                _nextIndex++;
                budget--;
            }

            // Fin de la secuencia
            if (_nextIndex >= _replay.events.Length)
            {
                if (loop)
                {
                    if (logEvents) Debug.Log("[Replay] Loop end — pausing before restart");
                    _loopPausing = true;
                    _resumeTime  = Time.time + loopPauseSec;
                }
                else
                {
                    _playing = false;
                    OnDisconnected?.Invoke();
                    WMSEventBus.RaiseDisconnected();
                }
            }
        }

        // ── Helpers ──────────────────────────────────────────────────────────

        private void BeginPlayback()
        {
            _playing = false;
            _loopPausing = false;
            ResetPlayhead();
            _playing = true;
        }

        private void ResetPlayhead()
        {
            _nextIndex = 0;
            _startTime = Time.time;
        }

        private IEnumerator LoadReplay()
        {
            // StreamingAssets en WebGL requiere UnityWebRequest porque el path
            // no es un file:// sino una URL relativa al servidor.
            string url = System.IO.Path.Combine(Application.streamingAssetsPath, replayFileName);
            #if !UNITY_WEBGL || UNITY_EDITOR
            if (!url.Contains("://"))
                url = "file://" + url;
            #endif

            using (UnityWebRequest req = UnityWebRequest.Get(url))
            {
                yield return req.SendWebRequest();

                if (req.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogError($"[Replay] Failed to load {url}: {req.error}");
                    yield break;
                }

                try
                {
                    _replay = JsonUtility.FromJson<Replay>(req.downloadHandler.text);
                    Debug.Log($"[Replay] Loaded {_replay.events.Length} events, duration {_replay.duration_sec}s");
                    OnConnected?.Invoke();
                    WMSEventBus.RaiseConnected();
                }
                catch (Exception ex)
                {
                    Debug.LogError($"[Replay] Parse failed: {ex.Message}");
                }
            }
        }

        private void DispatchEvent(WMSMessage msg)
        {
            if (msg == null || string.IsNullOrEmpty(msg.type)) return;
            if (logEvents) Debug.Log($"[Replay] -> {msg.type} @ {msg.location}");

            switch (msg.type)
            {
                case "alert":
                    OnAlert?.Invoke(msg);
                    WMSEventBus.RaiseAlert(msg);
                    break;
                case "narrative":
                    OnNarrative?.Invoke(msg);
                    WMSEventBus.RaiseNarrative(msg);
                    break;
            }
        }

        private void OnDisable()
        {
            _playing = false;
        }

        // ── Modelos internos del replay ───────────────────────────────────────

        [Serializable]
        public class Replay
        {
            public string name;
            public float  duration_sec;
            public bool   loop;
            public ReplayEvent[] events;
        }

        [Serializable]
        public class ReplayEvent
        {
            public float      t;
            public WMSMessage msg;
        }
    }
}
