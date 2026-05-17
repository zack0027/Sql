// =====================================================================
// WarehouseRack.shader
//
// Shader URP Lit-like con emission pulsante parametrizable.
// Diseñado para racks del gemelo digital: la base es gris neutro y la
// emission se modula desde C# vía MaterialPropertyBlock cuando hay alerta.
//
// Propiedades expuestas:
//   _BaseColor       - color del material en estado normal
//   _EmissionColor   - color HDR del pulso (rojo, ámbar, etc.)
//   _PulseIntensity  - 0..N escala global del pulso (0 = apagado)
//   _Smoothness      - 0..1 reflexión especular suave
//   _Metallic        - 0..1 metalicidad
//
// El AnomalyVisualizer setea _EmissionColor y _PulseIntensity desde C#.
// El Bloom global del Volume Profile amplifica visualmente los valores HDR.
//
// Referencias:
// - URP Shader Templates (oficial):
//   https://docs.unity3d.com/Packages/com.unity.render-pipelines.universal@17.0/manual/writing-shaders-urp-basic-unlit-structure.html
// - SRP Batcher CBUFFER requirements:
//   https://docs.unity3d.com/Manual/SRPBatcher.html
// =====================================================================

Shader "JCain/WarehouseRack"
{
    Properties
    {
        [MainColor] _BaseColor("Base color", Color) = (0.35, 0.35, 0.37, 1)
        [HDR] _EmissionColor("Emission color (HDR)", Color) = (0, 0, 0, 1)
        _PulseIntensity("Pulse intensity", Range(0, 5)) = 0
        _Smoothness("Smoothness", Range(0, 1)) = 0.35
        _Metallic("Metallic", Range(0, 1)) = 0.05
    }

    SubShader
    {
        Tags
        {
            "RenderType" = "Opaque"
            "RenderPipeline" = "UniversalPipeline"
            "Queue" = "Geometry"
        }

        // ---------------- ForwardLit pass ----------------
        Pass
        {
            Name "ForwardLit"
            Tags { "LightMode" = "UniversalForward" }

            HLSLPROGRAM
            #pragma vertex   Vert
            #pragma fragment Frag

            // Keywords URP estándar que necesitamos
            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS
            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS_CASCADE
            #pragma multi_compile _ _ADDITIONAL_LIGHTS_VERTEX _ADDITIONAL_LIGHTS
            #pragma multi_compile _ _ADDITIONAL_LIGHT_SHADOWS
            #pragma multi_compile _ _SHADOWS_SOFT
            #pragma multi_compile_fog

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

            // CBUFFER único por material: requerido para SRP Batcher.
            CBUFFER_START(UnityPerMaterial)
                float4 _BaseColor;
                float4 _EmissionColor;
                float  _PulseIntensity;
                float  _Smoothness;
                float  _Metallic;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS   : NORMAL;
            };

            struct Varyings
            {
                float4 positionHCS : SV_POSITION;
                float3 positionWS  : TEXCOORD0;
                float3 normalWS    : TEXCOORD1;
                float  fogCoord    : TEXCOORD2;
            };

            Varyings Vert(Attributes IN)
            {
                Varyings OUT;
                VertexPositionInputs posInputs = GetVertexPositionInputs(IN.positionOS.xyz);
                VertexNormalInputs   nrmInputs = GetVertexNormalInputs(IN.normalOS);

                OUT.positionHCS = posInputs.positionCS;
                OUT.positionWS  = posInputs.positionWS;
                OUT.normalWS    = nrmInputs.normalWS;
                OUT.fogCoord    = ComputeFogFactor(posInputs.positionCS.z);
                return OUT;
            }

            half4 Frag(Varyings IN) : SV_Target
            {
                // Datos de superficie estándar
                SurfaceData surface = (SurfaceData) 0;
                surface.albedo     = _BaseColor.rgb;
                surface.alpha      = _BaseColor.a;
                surface.metallic   = _Metallic;
                surface.smoothness = _Smoothness;
                surface.occlusion  = 1.0;
                surface.emission   = _EmissionColor.rgb * _PulseIntensity;
                surface.specular   = half3(0, 0, 0);

                // Datos de iluminación
                InputData lighting = (InputData) 0;
                lighting.positionWS         = IN.positionWS;
                lighting.normalWS           = normalize(IN.normalWS);
                lighting.viewDirectionWS    = GetWorldSpaceNormalizeViewDir(IN.positionWS);
                lighting.shadowCoord        = TransformWorldToShadowCoord(IN.positionWS);
                lighting.fogCoord           = IN.fogCoord;
                lighting.bakedGI            = SampleSH(lighting.normalWS);
                lighting.normalizedScreenSpaceUV = float2(0, 0);
                lighting.shadowMask         = half4(1, 1, 1, 1);

                half4 color = UniversalFragmentPBR(lighting, surface);
                color.rgb = MixFog(color.rgb, IN.fogCoord);
                return color;
            }
            ENDHLSL
        }

        // ---------------- ShadowCaster pass ----------------
        // Necesario para que el rack proyecte sombras correctas.
        Pass
        {
            Name "ShadowCaster"
            Tags { "LightMode" = "ShadowCaster" }

            ZWrite On
            ColorMask 0
            Cull Back

            HLSLPROGRAM
            #pragma vertex   ShadowVert
            #pragma fragment ShadowFrag

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Shadows.hlsl"

            CBUFFER_START(UnityPerMaterial)
                float4 _BaseColor;
                float4 _EmissionColor;
                float  _PulseIntensity;
                float  _Smoothness;
                float  _Metallic;
            CBUFFER_END

            float3 _LightDirection;
            float3 _LightPosition;

            struct AttributesShadow
            {
                float4 positionOS : POSITION;
                float3 normalOS   : NORMAL;
            };

            struct VaryingsShadow
            {
                float4 positionCS : SV_POSITION;
            };

            float4 GetShadowPositionHClip(AttributesShadow IN)
            {
                float3 positionWS = TransformObjectToWorld(IN.positionOS.xyz);
                float3 normalWS   = TransformObjectToWorldNormal(IN.normalOS);
                float4 positionCS = TransformWorldToHClip(
                    ApplyShadowBias(positionWS, normalWS, _LightDirection));
                #if UNITY_REVERSED_Z
                positionCS.z = min(positionCS.z, UNITY_NEAR_CLIP_VALUE);
                #else
                positionCS.z = max(positionCS.z, UNITY_NEAR_CLIP_VALUE);
                #endif
                return positionCS;
            }

            VaryingsShadow ShadowVert(AttributesShadow IN)
            {
                VaryingsShadow OUT;
                OUT.positionCS = GetShadowPositionHClip(IN);
                return OUT;
            }

            half4 ShadowFrag(VaryingsShadow IN) : SV_Target { return 0; }
            ENDHLSL
        }

        // ---------------- DepthOnly pass ----------------
        // Necesario para depth prepass, SSAO, y outlines screen-space si se usan.
        Pass
        {
            Name "DepthOnly"
            Tags { "LightMode" = "DepthOnly" }

            ZWrite On
            ColorMask 0
            Cull Back

            HLSLPROGRAM
            #pragma vertex   DepthVert
            #pragma fragment DepthFrag

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            CBUFFER_START(UnityPerMaterial)
                float4 _BaseColor;
                float4 _EmissionColor;
                float  _PulseIntensity;
                float  _Smoothness;
                float  _Metallic;
            CBUFFER_END

            struct AttributesD
            {
                float4 positionOS : POSITION;
            };

            struct VaryingsD
            {
                float4 positionCS : SV_POSITION;
            };

            VaryingsD DepthVert(AttributesD IN)
            {
                VaryingsD OUT;
                OUT.positionCS = TransformObjectToHClip(IN.positionOS.xyz);
                return OUT;
            }

            half4 DepthFrag(VaryingsD IN) : SV_Target { return 0; }
            ENDHLSL
        }
    }

    FallBack "Universal Render Pipeline/Lit"
}
