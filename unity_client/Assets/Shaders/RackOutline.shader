// =====================================================================
// RackOutline.shader
//
// Outline per-object usando la técnica "inverted hull":
//   1. Se expande cada vértice a lo largo de su normal en world space
//   2. Se renderiza solo el lado interno (Cull Front) en color sólido
//   3. El objeto real se dibuja encima ocupando el centro, dejando solo
//      el "halo" del hull expandido visible como un borde
//
// Ventajas:
//   - Funciona sin depth buffer extra ni renderer features
//   - Compatible con WebGL sin configuraciones especiales
//   - Costo: 1 draw call extra por objeto outlined
//
// Limitaciones:
//   - Funciona bien en geometría simple (cubos, prismas) - excelente
//     para racks. En modelos orgánicos puede tener artefactos en aristas
//     muy afiladas, pero no es nuestro caso.
//
// Uso típico:
//   - Asignar a un segundo material en el MeshRenderer del rack
//   - Setear _OutlineColor y _OutlineWidth desde C# vía MaterialPropertyBlock
//   - Cuando _OutlineWidth = 0, el outline desaparece
//
// Referencias:
// - ACM Studio Outline Shaders URP:
//   https://studio.uclaacm.com/byte-sized-tutorials/unity-urp-outline-shaders
// - Daniel Ilett Shader Toolbox - Inverted-Hull Outlines:
//   https://danielilett.com/shader-toolbox/hull-outlines/
// =====================================================================

Shader "JCain/RackOutline"
{
    Properties
    {
        [HDR] _OutlineColor("Outline color (HDR)", Color) = (1, 0.3, 0.1, 1)
        _OutlineWidth("Outline width", Range(0, 0.1)) = 0.02
    }

    SubShader
    {
        Tags
        {
            "RenderType" = "Opaque"
            "RenderPipeline" = "UniversalPipeline"
            "Queue" = "Geometry+1"
        }

        Pass
        {
            Name "Outline"
            Tags { "LightMode" = "UniversalForward" }

            // Renderizar solo el lado interno del hull expandido.
            // Esto deja solo el "anillo" exterior visible.
            Cull Front
            ZWrite On
            ZTest LEqual

            HLSLPROGRAM
            #pragma vertex   Vert
            #pragma fragment Frag

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            CBUFFER_START(UnityPerMaterial)
                float4 _OutlineColor;
                float  _OutlineWidth;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS   : NORMAL;
            };

            struct Varyings
            {
                float4 positionHCS : SV_POSITION;
            };

            Varyings Vert(Attributes IN)
            {
                Varyings OUT;

                // Expandir el vértice a lo largo de su normal en object space.
                // Multiplicar por _OutlineWidth controla qué tanto crece.
                float3 inflatedOS = IN.positionOS.xyz + normalize(IN.normalOS) * _OutlineWidth;
                OUT.positionHCS = TransformObjectToHClip(inflatedOS);
                return OUT;
            }

            half4 Frag(Varyings IN) : SV_Target
            {
                // Color sólido sin iluminación. El bloom del Volume Profile
                // amplifica los valores HDR si _OutlineColor pasa de 1.0.
                return _OutlineColor;
            }
            ENDHLSL
        }
    }

    FallBack Off
}
