using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using JCain.WMS.Connection;
using JCain.WMS.Models;

namespace JCain.WMS.UI
{
    /// <summary>
    /// Muestra las últimas N alertas en un panel lateral con scroll automático.
    /// Cada alerta se instancia desde un prefab que tiene un TMP_Text y un Image
    /// de fondo cuyo color varía por severidad.
    /// </summary>
    [DisallowMultipleComponent]
    public class AlertFeedUI : MonoBehaviour
    {
        [Header("References")]
        [SerializeField] private RectTransform contentContainer;
        [SerializeField] private AlertItemUI itemPrefab;
        [SerializeField] private ScrollRect scrollRect;

        [Header("Behaviour")]
        [SerializeField] private int maxItems = 20;

        private readonly Queue<AlertItemUI> _items = new Queue<AlertItemUI>(32);

        private void OnEnable()  => WMSEventBus.OnAlert += HandleAlert;
        private void OnDisable() => WMSEventBus.OnAlert -= HandleAlert;

        private void HandleAlert(WMSMessage msg)
        {
            if (msg == null) return;
            if (itemPrefab == null || contentContainer == null)
            {
                Debug.LogWarning("[AlertFeedUI] Missing references in inspector");
                return;
            }

            // Reciclar el más viejo si pasamos el tope, en vez de instanciar sin parar.
            AlertItemUI item;
            if (_items.Count >= maxItems)
            {
                item = _items.Dequeue();
                item.transform.SetAsLastSibling();
            }
            else
            {
                item = Instantiate(itemPrefab, contentContainer);
            }

            Severity sev = SeverityHelper.Parse(msg.severity);
            item.Render(msg, sev);
            _items.Enqueue(item);

            // Scroll al fondo para mostrar la más reciente.
            Canvas.ForceUpdateCanvases();
            if (scrollRect != null) scrollRect.verticalNormalizedPosition = 0f;
        }
    }

    /// <summary>
    /// Componente del prefab de cada ítem del feed.
    /// Estructura del prefab: Panel (Image) > VerticalLayoutGroup > TMP_Text x2.
    /// </summary>
    public class AlertItemUI : MonoBehaviour
    {
        [SerializeField] private TMP_Text headerLabel;
        [SerializeField] private TMP_Text detailLabel;
        [SerializeField] private Image background;

        private static readonly Color CriticalBg = new Color(0.55f, 0.10f, 0.10f, 0.95f);
        private static readonly Color HighBg     = new Color(0.55f, 0.30f, 0.05f, 0.95f);
        private static readonly Color MediumBg   = new Color(0.40f, 0.40f, 0.10f, 0.95f);
        private static readonly Color NormalBg   = new Color(0.20f, 0.20f, 0.22f, 0.90f);

        public void Render(WMSMessage msg, Severity sev)
        {
            if (background != null)
            {
                background.color = sev switch
                {
                    Severity.Critical => CriticalBg,
                    Severity.High     => HighBg,
                    Severity.Medium   => MediumBg,
                    _                 => NormalBg,
                };
            }

            if (headerLabel != null)
                headerLabel.text = $"{msg.severity?.ToUpperInvariant()} · {msg.location}";

            if (detailLabel != null)
                detailLabel.text =
                    $"{msg.movement_type} · {msg.sku}\n" +
                    $"qty {msg.quantity} · {msg.duration_sec}s\n" +
                    $"{msg.rule_reasons}";
        }
    }
}
