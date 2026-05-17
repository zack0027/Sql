#if UNITY_EDITOR
using UnityEditor;
using UnityEngine;
using JCain.WMS.Visualization;

namespace JCain.WMS.EditorTools
{
    /// <summary>
    /// Genera la grilla de racks del almacén desde el menú
    /// Tools > Warehouse > Generate Grid. Filas A-F, columnas 1-6 por defecto.
    /// </summary>
    public class WarehouseGridGenerator : EditorWindow
    {
        private int rows = 6;
        private int cols = 6;
        private float spacing = 2.5f;
        private Vector3 rackSize = new Vector3(1.5f, 2.5f, 1.0f);
        private Material rackMaterial;
        private Material outlineMaterial;

        [MenuItem("Tools/Warehouse/Generate Grid")]
        public static void Open() =>
            GetWindow<WarehouseGridGenerator>("Warehouse Grid");

        private void OnGUI()
        {
            GUILayout.Label("Grid configuration", EditorStyles.boldLabel);
            rows = EditorGUILayout.IntSlider("Rows (letters)", rows, 2, 12);
            cols = EditorGUILayout.IntSlider("Columns", cols, 2, 20);
            spacing = EditorGUILayout.Slider("Spacing", spacing, 1f, 5f);
            rackSize = EditorGUILayout.Vector3Field("Rack size", rackSize);
            rackMaterial = (Material)EditorGUILayout.ObjectField(
                "Rack material", rackMaterial, typeof(Material), false);
            outlineMaterial = (Material)EditorGUILayout.ObjectField(
                "Outline material (optional)", outlineMaterial, typeof(Material), false);

            EditorGUILayout.Space();

            if (GUILayout.Button("Generate"))
            {
                Generate();
            }

            if (GUILayout.Button("Clear existing grid"))
            {
                GameObject existing = GameObject.Find("_Warehouse_Grid");
                if (existing != null) DestroyImmediate(existing);
            }
        }

        private void Generate()
        {
            GameObject parent = GameObject.Find("_Warehouse_Grid");
            if (parent != null) DestroyImmediate(parent);
            parent = new GameObject("_Warehouse_Grid");

            for (int r = 0; r < rows; r++)
            {
                char letter = (char)('A' + r);
                for (int c = 1; c <= cols; c++)
                {
                    string code = $"{letter}-{c:000}";
                    GameObject rack = GameObject.CreatePrimitive(PrimitiveType.Cube);
                    rack.name = $"Rack_{code}";
                    rack.transform.SetParent(parent.transform);
                    rack.transform.position = new Vector3(
                        (c - 1) * spacing, rackSize.y / 2f, r * spacing);
                    rack.transform.localScale = rackSize;

                    Renderer rend = rack.GetComponent<Renderer>();
                    if (outlineMaterial != null && rackMaterial != null)
                    {
                        // Dos materiales: principal + outline
                        rend.sharedMaterials = new Material[] { rackMaterial, outlineMaterial };
                    }
                    else if (rackMaterial != null)
                    {
                        rend.sharedMaterial = rackMaterial;
                    }

                    RackId id = rack.AddComponent<RackId>();
                    id.SetLocationCode(code);

                    // Suavizar normales para que el outline inverted-hull no tenga huecos.
                    rack.AddComponent<SmoothNormalsAtRuntime>();
                }
            }

            Debug.Log($"[WarehouseGridGenerator] Generated {rows * cols} racks");
            Selection.activeGameObject = parent;
        }
    }
}
#endif
