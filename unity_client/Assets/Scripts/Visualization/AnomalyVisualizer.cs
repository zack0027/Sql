using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using JCain.WMS.Connection;
using JCain.WMS.Models;

namespace JCain.WMS.Visualization
{
    /// <summary>
    /// Escucha WMSEventBus.OnAlert y hace pulsar el rack correspondiente.
    ///
    /// Modula tres cosas en cada frame de la corutina:
    ///   - _PulseIntensity del shader principal (WarehouseRack)
    ///   - _EmissionColor del shader principal
    ///   - _OutlineWidth del shader de outline (RackOutline)
    ///
    /// Todo vía MaterialPropertyBlock para preservar el batching de URP.
    /// El rack tiene un MeshRenderer con DOS materiales en su array:
    ///   [0] = Material con WarehouseRack shader
    ///   [1] = Material con RackOutline shader
    /// Los índices se setean por inspector o por convención.
    /// </summary>
    [DisallowMultipleComponent]
    public class AnomalyVisualizer : MonoBehaviour
    {
        [Header("Material slots")]
        [Tooltip("Índice del material principal en el MeshRenderer.materials array.")]
        [SerializeField] private int rackMaterialIndex = 0;
        [Tooltip("Índice del material outline. -1 si no hay outline.")]
        [SerializeField] private int outlineMaterialIndex = 1;

        [Header("Shader properties")]
        [SerializeField] private string emissionProperty = "_EmissionColor";
        [SerializeField] private string pulseIntensityProperty = "_PulseIntensity";
        [SerializeField] private string outlineColorProperty = "_OutlineColor";
        [SerializeField] private string outlineWidthProperty = "_OutlineWidth";

        [Header("Pulse")]
        [SerializeField] private float pulseHz = 2f;
        [SerializeField] private AnimationCurve pulseEnvelope =
            AnimationCurve.EaseInOut(0f, 1f, 1f, 0f);

        [Header("Outline")]
        [Tooltip("Ancho máximo del outline en el pico del pulso.")]
        [SerializeField] private float maxOutlineWidth = 0.04f;
        [Tooltip("Multiplicador del color outline respecto al emission.")]
        [SerializeField] private float outlineColorBoost = 1.2f;

        private readonly Dictionary<string, Coroutine> _running =
            new Dictionary<string, Coroutine>();

        private MaterialPropertyBlock _mpbRack;
        private MaterialPropertyBlock _mpbOutline;
        private int _emissionId;
        private int _pulseIntensityId;
        private int _outlineColorId;
        private int _outlineWidthId;

        private void Awake()
        {
            _mpbRack    = new MaterialPropertyBlock();
            _mpbOutline = new MaterialPropertyBlock();
            _emissionId       = Shader.PropertyToID(emissionProperty);
            _pulseIntensityId = Shader.PropertyToID(pulseIntensityProperty);
            _outlineColorId   = Shader.PropertyToID(outlineColorProperty);
            _outlineWidthId   = Shader.PropertyToID(outlineWidthProperty);
        }

        private void OnEnable()  => WMSEventBus.OnAlert += HandleAlert;
        private void OnDisable() => WMSEventBus.OnAlert -= HandleAlert;

        private void HandleAlert(WMSMessage msg)
        {
            if (msg == null || string.IsNullOrEmpty(msg.location)) return;
            if (RackRegistry.Instance == null) return;

            if (!RackRegistry.Instance.TryGet(msg.location, out RackId rack))
            {
                Debug.LogWarning($"[AnomalyVisualizer] No rack for {msg.location}");
                return;
            }

            Severity sev = SeverityHelper.Parse(msg.severity);
            if (sev == Severity.Normal) return;

            if (_running.TryGetValue(msg.location, out Coroutine existing) && existing != null)
                StopCoroutine(existing);

            _running[msg.location] = StartCoroutine(PulseRack(rack, sev));
        }

        private IEnumerator PulseRack(RackId rack, Severity sev)
        {
            Renderer rend = rack.GetComponentInChildren<Renderer>();
            if (rend == null) yield break;

            Color baseColor = SeverityHelper.ToColor(sev);
            float duration  = SeverityHelper.PulseDuration(sev);
            float elapsed   = 0f;

            while (elapsed < duration)
            {
                float envelope  = pulseEnvelope.Evaluate(elapsed / duration);
                float wave      = 0.5f + 0.5f * Mathf.Sin(elapsed * pulseHz * Mathf.PI * 2f);
                float intensity = envelope * wave;

                ApplyPulse(rend, baseColor, intensity);

                elapsed += Time.deltaTime;
                yield return null;
            }

            ApplyPulse(rend, baseColor, 0f);
            _running[rack.LocationCode] = null;
        }

        /// <summary>
        /// Aplica la intensidad actual del pulso a los dos materiales del rack.
        /// </summary>
        private void ApplyPulse(Renderer rend, Color baseColor, float intensity01)
        {
            // Material principal: emission color + intensidad
            rend.GetPropertyBlock(_mpbRack, rackMaterialIndex);
            _mpbRack.SetColor(_emissionId, baseColor);
            _mpbRack.SetFloat(_pulseIntensityId, intensity01);
            rend.SetPropertyBlock(_mpbRack, rackMaterialIndex);

            // Material outline (opcional)
            if (outlineMaterialIndex >= 0 && outlineMaterialIndex < rend.sharedMaterials.Length)
            {
                rend.GetPropertyBlock(_mpbOutline, outlineMaterialIndex);
                _mpbOutline.SetColor(_outlineColorId, baseColor * outlineColorBoost);
                _mpbOutline.SetFloat(_outlineWidthId, maxOutlineWidth * intensity01);
                rend.SetPropertyBlock(_mpbOutline, outlineMaterialIndex);
            }
        }
    }
}
