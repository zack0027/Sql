using System;
using System.Collections;
using System.Collections.Generic;
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
    /// Se carga desde StreamingAssets porque ese folder se serializa tal cual
    /// en WebGL builds y queda accesible vía UnityWebRequest.
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

        [Header("Debug")]
        [SerializeField] private bool logEvents = false;

        // Mismos eventos que WMSConnection: cualquier subscriber no nota la diferencia.
        public static event Action OnConnected;
        public static event Action OnDisconnected;
        public static event Action<WMSMessage> OnAlert;
        public static event Action<WMSMessage> OnNarrative;

        private Replay _replay;
        private Coroutine _playbackCoroutine;

        private IEnumerator Start()
        {
            Application.runInBackground = true;
            yield return LoadReplay();
            if (autoStart && _replay != null)
                _playbackCoroutine = StartCoroutine(Playback());
        }

        private IEnumerator LoadReplay()
        {
            // StreamingAssets en WebGL requiere UnityWebRequest porque el path
            // no es un file:// sino una URL relativa al servidor.
            string url = System.IO.Path.Combine(Application.streamingAssetsPath, replayFileName);
            #if !UNITY_WEBGL || UNITY_EDITOR
            // En editor y standalone, prefijar file:// si no lo tiene
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

        private IEnumerator Playback()
        {
            do
            {
                float t0 = Time.time;
                int idx = 0;

                while (idx < _replay.events.Length)
                {
                    ReplayEvent ev = _replay.events[idx];
                    float targetTime = ev.t / Mathf.Max(0.01f, playbackSpeed);

                    // Espera hasta el momento adecuado
                    float wait = targetTime - (Time.time - t0);
                    if (wait > 0) yield return new WaitForSeconds(wait);

                    DispatchEvent(ev.msg);
                    idx++;
                }

                if (loop)
                {
                    if (logEvents) Debug.Log("[Replay] Loop restart");
                    yield return new WaitForSeconds(loopPauseSec);
                }
            } while (loop);

            OnDisconnected?.Invoke();
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
                default: break;
            }
        }

        private void OnDisable()
        {
            if (_playbackCoroutine != null)
                StopCoroutine(_playbackCoroutine);
        }

        // ---- Modelos internos del replay ----

        [Serializable]
        public class Replay
        {
            public string name;
            public float duration_sec;
            public bool loop;
            public ReplayEvent[] events;
        }

        [Serializable]
        public class ReplayEvent
        {
            public float t;
            public WMSMessage msg;
        }
    }
}
