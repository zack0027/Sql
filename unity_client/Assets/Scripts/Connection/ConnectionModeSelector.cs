using UnityEngine;

namespace JCain.WMS.Connection
{
    /// <summary>
    /// Selecciona qué fuente de datos está activa: WebSocket en vivo o replay.
    /// Habilita el GameObject correspondiente al arrancar y deja el otro inactivo.
    /// Pensado para que en Unity Editor puedas alternar fácil, y para que el
    /// build de GitHub Pages tenga forzado el modo Replay sin tocar código.
    /// </summary>
    [DisallowMultipleComponent]
    public class ConnectionModeSelector : MonoBehaviour
    {
        public enum Mode { Replay, Live }

        [SerializeField] private Mode initialMode = Mode.Replay;

        [Header("Targets")]
        [SerializeField] private GameObject liveConnection;
        [SerializeField] private GameObject replayConnection;

        private void Awake()
        {
            ApplyMode(initialMode);
        }

        public void ApplyMode(Mode mode)
        {
            if (liveConnection   != null) liveConnection.SetActive(mode == Mode.Live);
            if (replayConnection != null) replayConnection.SetActive(mode == Mode.Replay);
            Debug.Log($"[ConnectionModeSelector] Active mode: {mode}");
        }

        // Convenience hooks (atables desde botones UI si quieres exponerlo)
        public void SwitchToLive()   => ApplyMode(Mode.Live);
        public void SwitchToReplay() => ApplyMode(Mode.Replay);
    }
}
