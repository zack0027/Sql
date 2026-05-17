using System.Collections.Generic;
using UnityEngine;

namespace JCain.WMS.Visualization
{
    /// <summary>
    /// Indexa todos los racks de la escena al arrancar y permite resolver
    /// código de ubicación -> Transform en O(1).
    ///
    /// Patrón: singleton de escena (no DontDestroyOnLoad porque cada escena
    /// tiene su propio layout de almacén).
    /// </summary>
    [DisallowMultipleComponent]
    public class RackRegistry : MonoBehaviour
    {
        public static RackRegistry Instance { get; private set; }

        private readonly Dictionary<string, RackId> _byCode =
            new Dictionary<string, RackId>(128);

        [SerializeField] private bool logIndex = false;

        private void Awake()
        {
            if (Instance != null && Instance != this)
            {
                Destroy(this);
                return;
            }
            Instance = this;
            IndexAll();
        }

        private void OnDestroy()
        {
            if (Instance == this) Instance = null;
        }

        /// <summary>
        /// Recorre la escena buscando todos los RackId. Incluye inactivos.
        /// </summary>
        public void IndexAll()
        {
            _byCode.Clear();
            // FindObjectsByType es el reemplazo recomendado en Unity 6 de FindObjectsOfType.
            // FindObjectsSortMode.None evita el costo del sort cuando no nos importa orden.
            RackId[] all = FindObjectsByType<RackId>(
                FindObjectsInactive.Include, FindObjectsSortMode.None);

            foreach (RackId r in all)
            {
                if (string.IsNullOrEmpty(r.LocationCode)) continue;
                if (_byCode.ContainsKey(r.LocationCode))
                {
                    Debug.LogWarning($"[RackRegistry] Duplicate code: {r.LocationCode} on {r.name}");
                    continue;
                }
                _byCode.Add(r.LocationCode, r);
            }

            if (logIndex)
                Debug.Log($"[RackRegistry] Indexed {_byCode.Count} racks");
        }

        public bool TryGet(string locationCode, out RackId rack) =>
            _byCode.TryGetValue(locationCode, out rack);

        public int Count => _byCode.Count;
    }
}
