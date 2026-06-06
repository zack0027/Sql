using System;
using System.Threading.Tasks;
using NativeWebSocket;
using UnityEngine;
using JCain.WMS.Models;

namespace JCain.WMS.Connection
{
    /// <summary>
    /// Cliente WebSocket que se conecta al backend FastAPI y dispara eventos C#
    /// cuando llegan mensajes. No conoce racks ni UI: solo parsea y notifica.
    ///
    /// Patrón de diseño: pub/sub con eventos estáticos.
    /// AnomalyVisualizer, AlertFeedUI y NarrativePanelUI se suscriben en OnEnable.
    /// </summary>
    [DisallowMultipleComponent]
    public class WMSConnection : MonoBehaviour
    {
        [Header("Connection")]
        [Tooltip("URL del WebSocket del backend. Ej: ws://localhost:8000/ws/events")]
        [SerializeField] private string serverUrl = "ws://localhost:8000/ws/events";

        [Tooltip("Reintentar conexión automáticamente si se cae.")]
        [SerializeField] private bool autoReconnect = true;

        [Tooltip("Segundos entre intentos de reconexión.")]
        [SerializeField] private float reconnectDelaySec = 3f;

        [Header("Debug")]
        [SerializeField] private bool logIncoming = false;

        // Eventos públicos. Cualquier MonoBehaviour puede suscribirse.
        public static event Action OnConnected;
        public static event Action OnDisconnected;
        public static event Action<WMSMessage> OnAlert;
        public static event Action<WMSMessage> OnNarrative;

        private WebSocket _socket;
        private bool _shuttingDown;
        private float _nextReconnectTime;

        private async void Start()
        {
            // Requerido para WebGL: sin esto, el game loop se pausa al perder foco
            // del tab y los callbacks del WebSocket no se procesan.
            Application.runInBackground = true;

            await ConnectAsync();
        }

        private void Update()
        {
            // En plataformas nativas (no WebGL) hay que drenar la queue cada frame.
            // En WebGL el preprocesador lo compila como no-op (los callbacks llegan
            // directo desde JS al thread principal).
            #if !UNITY_WEBGL || UNITY_EDITOR
            _socket?.DispatchMessageQueue();
            #endif

            // Reconexión automática con throttling.
            if (autoReconnect && !_shuttingDown &&
                _socket != null && _socket.State == WebSocketState.Closed &&
                Time.time >= _nextReconnectTime)
            {
                _nextReconnectTime = Time.time + reconnectDelaySec;
                _ = ConnectAsync();
            }
        }

        private async Task ConnectAsync()
        {
            try
            {
                _socket = new WebSocket(serverUrl);

                _socket.OnOpen += () =>
                {
                    Debug.Log($"[WMS] Connected to {serverUrl}");
                    OnConnected?.Invoke();
                    WMSEventBus.RaiseConnected();
                };

                _socket.OnError += err =>
                {
                    Debug.LogWarning($"[WMS] WebSocket error: {err}");
                };

                _socket.OnClose += code =>
                {
                    Debug.Log($"[WMS] Disconnected. Code: {code}");
                    OnDisconnected?.Invoke();
                    WMSEventBus.RaiseDisconnected();
                };

                _socket.OnMessage += HandleMessage;

                await _socket.Connect();
            }
            catch (Exception ex)
            {
                Debug.LogError($"[WMS] Connect failed: {ex.Message}");
            }
        }

        private void HandleMessage(byte[] bytes)
        {
            string json = System.Text.Encoding.UTF8.GetString(bytes);
            if (logIncoming) Debug.Log($"[WMS] <- {json}");

            // Sondear tipo primero. Si el JSON viene mal formado, no crashea el resto.
            MessageTypeProbe probe;
            try
            {
                probe = JsonUtility.FromJson<MessageTypeProbe>(json);
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[WMS] Bad JSON: {ex.Message}");
                return;
            }

            if (probe == null || string.IsNullOrEmpty(probe.type)) return;

            WMSMessage msg;
            try
            {
                msg = JsonUtility.FromJson<WMSMessage>(json);
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[WMS] Deserialize failed: {ex.Message}");
                return;
            }

            switch (probe.type)
            {
                case "anomaly":
                    OnAlert?.Invoke(msg);
                    WMSEventBus.RaiseAlert(msg);
                    break;
                case "narration":
                    OnNarrative?.Invoke(msg);
                    WMSEventBus.RaiseNarrative(msg);
                    break;
                case "hello":     Debug.Log("[WMS] Hello received"); break;
                default:          Debug.Log($"[WMS] Unknown type: {probe.type}"); break;
            }
        }

        private async void OnApplicationQuit()
        {
            _shuttingDown = true;
            if (_socket != null && _socket.State == WebSocketState.Open)
                await _socket.Close();
        }

        private async void OnDisable()
        {
            // En el editor, al detener Play, queremos cerrar el socket limpio.
            if (_socket != null && _socket.State == WebSocketState.Open)
                await _socket.Close();
        }
    }
}
