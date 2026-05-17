using System;
using JCain.WMS.Models;

namespace JCain.WMS.Connection
{
    /// <summary>
    /// Bus central de eventos. Tanto WMSConnection (live) como ReplayConnection
    /// (estático) publican aquí, y los componentes UI/visuales se suscriben aquí.
    ///
    /// Patrón: pub/sub con eventos estáticos. Como es static, no necesita
    /// referencia en Inspector. Los suscriptores se atan en OnEnable y
    /// se desatan en OnDisable.
    ///
    /// Beneficio práctico: cambiar entre modo live y replay es solo activar
    /// el GameObject correspondiente. Los UI no se enteran.
    /// </summary>
    public static class WMSEventBus
    {
        public static event Action OnConnected;
        public static event Action OnDisconnected;
        public static event Action<WMSMessage> OnAlert;
        public static event Action<WMSMessage> OnNarrative;

        public static void RaiseConnected()             => OnConnected?.Invoke();
        public static void RaiseDisconnected()          => OnDisconnected?.Invoke();
        public static void RaiseAlert(WMSMessage m)     => OnAlert?.Invoke(m);
        public static void RaiseNarrative(WMSMessage m) => OnNarrative?.Invoke(m);
    }
}
