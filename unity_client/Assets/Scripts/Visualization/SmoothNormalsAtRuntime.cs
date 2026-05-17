using System.Collections.Generic;
using UnityEngine;

namespace JCain.WMS.Visualization
{
    /// <summary>
    /// Para que el shader inverted hull produzca outlines limpios en geometría
    /// con aristas duras (como un cubo primitivo de Unity), necesitamos que
    /// los vértices que comparten posición compartan también su normal.
    ///
    /// Sin esto, las tres normales en cada esquina del cubo apuntan en 3
    /// direcciones distintas y al expandirlas se separan, dejando huecos
    /// triangulares visibles en las esquinas del outline.
    ///
    /// Este componente promedia las normales de vértices co-localizados al
    /// arrancar. El mesh original NO se modifica (se trabaja sobre una copia).
    ///
    /// Aplicar a cada rack GameObject. Si usas un prefab compartido, mejor
    /// usar el script editor MeshNormalSmoother en /Editor para precalcularlo.
    /// </summary>
    [RequireComponent(typeof(MeshFilter))]
    [DisallowMultipleComponent]
    public class SmoothNormalsAtRuntime : MonoBehaviour
    {
        [Tooltip("Tolerancia espacial para considerar dos vértices co-localizados.")]
        [SerializeField] private float positionTolerance = 0.0001f;

        private void Awake()
        {
            MeshFilter mf = GetComponent<MeshFilter>();
            if (mf == null || mf.sharedMesh == null) return;

            // Copia para no contaminar el asset original ni los demás racks.
            Mesh smoothed = Instantiate(mf.sharedMesh);
            smoothed.name = mf.sharedMesh.name + "_SmoothNormals";
            SmoothMesh(smoothed);
            mf.sharedMesh = smoothed;
        }

        private void SmoothMesh(Mesh mesh)
        {
            Vector3[] vertices = mesh.vertices;
            Vector3[] normals  = mesh.normals;

            // Agrupar vértices por posición aproximada.
            // Clave: hash de (x, y, z) redondeada a la tolerancia.
            var groups = new Dictionary<Vector3, List<int>>();
            for (int i = 0; i < vertices.Length; i++)
            {
                Vector3 key = QuantizePosition(vertices[i], positionTolerance);
                if (!groups.TryGetValue(key, out List<int> bucket))
                {
                    bucket = new List<int>(8);
                    groups.Add(key, bucket);
                }
                bucket.Add(i);
            }

            // Calcular normal promedio por grupo y reasignar.
            foreach (List<int> bucket in groups.Values)
            {
                if (bucket.Count <= 1) continue;

                Vector3 sum = Vector3.zero;
                foreach (int idx in bucket) sum += normals[idx];
                Vector3 avg = sum.normalized;

                foreach (int idx in bucket) normals[idx] = avg;
            }

            mesh.normals = normals;
            mesh.RecalculateTangents(); // por si algún shader las usa
        }

        private static Vector3 QuantizePosition(Vector3 v, float tolerance)
        {
            float inv = 1f / Mathf.Max(tolerance, 1e-6f);
            return new Vector3(
                Mathf.Round(v.x * inv) / inv,
                Mathf.Round(v.y * inv) / inv,
                Mathf.Round(v.z * inv) / inv);
        }
    }
}
