using System.Collections;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using JCain.WMS.Connection;
using JCain.WMS.Models;

namespace JCain.WMS.UI
{
    /// <summary>
    /// Panel grande que muestra la narrativa generada por el LLM (Ollama).
    /// Se abre con fade, queda visible unos segundos, y se cierra con fade.
    /// Si llega otra narrativa antes, la actual se reemplaza.
    /// </summary>
    [DisallowMultipleComponent]
    public class NarrativePanelUI : MonoBehaviour
    {
        [Header("References")]
        [SerializeField] private CanvasGroup panelCanvasGroup;
        [SerializeField] private TMP_Text locationLabel;
        [SerializeField] private TMP_Text narrativeBody;
        [SerializeField] private TMP_Text causeLabel;
        [SerializeField] private TMP_Text actionLabel;
        [SerializeField] private TMP_Text sourceTag;

        [Header("Animation")]
        [SerializeField] private float fadeInSec = 0.4f;
        [SerializeField] private float visibleSec = 8f;
        [SerializeField] private float fadeOutSec = 0.6f;

        private Coroutine _current;

        private void Awake()
        {
            if (panelCanvasGroup != null)
            {
                panelCanvasGroup.alpha = 0f;
                panelCanvasGroup.blocksRaycasts = false;
            }
        }

        private void OnEnable()  => WMSEventBus.OnNarrative += HandleNarrative;
        private void OnDisable() => WMSEventBus.OnNarrative -= HandleNarrative;

        private void HandleNarrative(WMSMessage msg)
        {
            if (msg == null) return;
            if (panelCanvasGroup == null)
            {
                Debug.LogWarning("[NarrativePanelUI] Missing canvas group");
                return;
            }

            // Pisar la narrativa anterior si todavía estaba on screen.
            if (_current != null) StopCoroutine(_current);
            _current = StartCoroutine(ShowNarrative(msg));
        }

        private IEnumerator ShowNarrative(WMSMessage msg)
        {
            if (locationLabel  != null) locationLabel.text  = msg.location;
            if (narrativeBody  != null) narrativeBody.text  = msg.narrative;
            if (causeLabel     != null) causeLabel.text     = $"Causa probable: {msg.likely_cause}";
            if (actionLabel    != null) actionLabel.text    = $"Acción: {msg.recommended_action}";
            if (sourceTag      != null)
                sourceTag.text = $"{msg.source} · {msg.model} · {msg.latency_sec:F1}s";

            yield return Fade(0f, 1f, fadeInSec);
            panelCanvasGroup.blocksRaycasts = true;

            yield return new WaitForSeconds(visibleSec);

            panelCanvasGroup.blocksRaycasts = false;
            yield return Fade(1f, 0f, fadeOutSec);

            _current = null;
        }

        private IEnumerator Fade(float from, float to, float duration)
        {
            float elapsed = 0f;
            while (elapsed < duration)
            {
                panelCanvasGroup.alpha = Mathf.Lerp(from, to, elapsed / duration);
                elapsed += Time.deltaTime;
                yield return null;
            }
            panelCanvasGroup.alpha = to;
        }
    }
}
