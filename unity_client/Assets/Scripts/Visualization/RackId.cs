using UnityEngine;

namespace JCain.WMS.Visualization
{
    /// <summary>
    /// Identifica una ubicación del almacén. Va en cada GameObject rack.
    /// El locationCode debe coincidir exactamente con el que manda el backend
    /// (ej. "A-001", "C-018", "MAQ-PLT-04").
    /// </summary>
    [DisallowMultipleComponent]
    public class RackId : MonoBehaviour
    {
        [SerializeField] private string locationCode = "A-001";

        public string LocationCode => locationCode;

        // Permite asignar el código por script al generar la grilla.
        public void SetLocationCode(string code) => locationCode = code;

        private void OnValidate()
        {
            if (!string.IsNullOrEmpty(locationCode))
                gameObject.name = $"Rack_{locationCode}";
        }
    }
}
