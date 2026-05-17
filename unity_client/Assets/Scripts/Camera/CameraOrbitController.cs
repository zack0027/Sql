using UnityEngine;

namespace JCain.WMS.CameraControl
{
    /// <summary>
    /// Cámara orbital: drag con botón derecho rota, scroll hace zoom, drag con
    /// botón medio hace pan. Usa Input legacy para no agregar dependencia del
    /// nuevo Input System. Si tu proyecto usa Input System, ver consultas/.
    /// </summary>
    [DisallowMultipleComponent]
    [RequireComponent(typeof(Camera))]
    public class CameraOrbitController : MonoBehaviour
    {
        [Header("Target")]
        [SerializeField] private Transform pivot;
        [SerializeField] private Vector3 fallbackPivot = new Vector3(0f, 1f, 0f);

        [Header("Orbit")]
        [SerializeField] private float distance = 15f;
        [SerializeField] private float minDistance = 5f;
        [SerializeField] private float maxDistance = 40f;
        [SerializeField] private float rotateSpeed = 200f;
        [SerializeField] private float zoomSpeed = 5f;
        [SerializeField] private float panSpeed = 0.05f;
        [SerializeField] private float smoothTime = 0.1f;

        [Header("Initial angles")]
        [SerializeField] private float pitch = 35f;
        [SerializeField] private float yaw = 45f;

        private Vector3 _pivotVelocity;
        private Vector3 _targetPivot;

        private void Start()
        {
            _targetPivot = pivot != null ? pivot.position : fallbackPivot;
            UpdateCameraTransform();
        }

        private void LateUpdate()
        {
            // Rotación con botón derecho.
            if (Input.GetMouseButton(1))
            {
                yaw   += Input.GetAxis("Mouse X") * rotateSpeed * Time.deltaTime;
                pitch -= Input.GetAxis("Mouse Y") * rotateSpeed * Time.deltaTime;
                pitch = Mathf.Clamp(pitch, 10f, 85f);
            }

            // Pan con botón medio.
            if (Input.GetMouseButton(2))
            {
                Vector3 right = transform.right * -Input.GetAxis("Mouse X") * panSpeed * distance;
                Vector3 up    = transform.up    * -Input.GetAxis("Mouse Y") * panSpeed * distance;
                _targetPivot += right + up;
            }

            // Zoom con scroll.
            float scroll = Input.GetAxis("Mouse ScrollWheel");
            if (Mathf.Abs(scroll) > 0.0001f)
            {
                distance -= scroll * zoomSpeed;
                distance = Mathf.Clamp(distance, minDistance, maxDistance);
            }

            // Smoothing del pivot para que el pan no se sienta brusco.
            if (pivot != null)
                pivot.position = Vector3.SmoothDamp(pivot.position, _targetPivot,
                    ref _pivotVelocity, smoothTime);

            UpdateCameraTransform();
        }

        private void UpdateCameraTransform()
        {
            Vector3 pivotPos = pivot != null ? pivot.position : _targetPivot;
            Quaternion rot = Quaternion.Euler(pitch, yaw, 0f);
            Vector3 offset = rot * new Vector3(0f, 0f, -distance);
            transform.position = pivotPos + offset;
            transform.rotation = rot;
        }
    }
}
