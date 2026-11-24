import {
  AbsoluteFill,
  Composition,
  Easing,
  interpolate,
  registerRoot,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "raea";
import { Model } from "raea/3d";
import { LinearRgba, Srgba } from "raea/color";
import { AmbientLight, DirectionalLight } from "raea/light";
import { StandardMaterial } from "raea/pbr";
import { Transform } from "raea/transform";
import { Camera3d } from "raea/camera";
import cfg from "./scene3d_config.json";

const FONT_TC = "'Noto Sans CJK TC', 'Noto Sans TC', sans-serif";

function Anatomy3DTemplate() {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const progress = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  const angle = interpolate(progress, [0, 1], [-0.75, 0.75]);
  const rStart = typeof cfg.camera_radius_start === "number" ? cfg.camera_radius_start : 26;
  const rEnd = typeof cfg.camera_radius_end === "number" ? cfg.camera_radius_end : 21.5;
  const radius = interpolate(progress, [0, 1], [rStart, rEnd]);
  const target: [number, number, number] = [0, 1.5, -1];
  const camX = target[0] + radius * Math.sin(angle);
  const camZ = target[2] + radius * Math.cos(angle);
  const camY = interpolate(progress, [0, 1], [4.8, 2.8]);

  return (
    <AbsoluteFill style={{ background: "#0f172a", fontFamily: FONT_TC }}>
      <Camera3d
        transform={Transform.fromXyz(camX, camY, camZ).lookingAt(target)}
        projection={{ Perspective: { fov: (38 * Math.PI) / 180 } }}
      />
      <AmbientLight brightness={450} />
      <DirectionalLight
        transform={Transform.fromXyz(12, 18, 15).lookingAt(target)}
        illuminance={12000}
        shadow_maps_enabled
      />
      <DirectionalLight
        transform={Transform.fromXyz(-12, 8, -10).lookingAt(target)}
        illuminance={5500}
      />

      {/* 主體骨質/組織：半透明材質以透視內部構造 */}
      <Model src={staticFile(cfg.core_glb)} position={[0, 0, 0]} allowOverlap>
        <StandardMaterial
          base_color={Srgba.hex("#e2e8f0").with_alpha(0.32)}
          alpha_mode="Blend"
          perceptual_roughness={0.35}
          double_sided
        />
      </Model>

      {/* 次層神經血管束：高對比暖紅發光材質 */}
      {cfg.overlay_glb ? (
        <Model src={staticFile(cfg.overlay_glb)} position={[0, 0, 0]} allowOverlap>
          <StandardMaterial
            base_color="#ef4444"
            emissive={LinearRgba.from(Srgba.hex("#f97316")).mul(0.8)}
            perceptual_roughness={0.3}
            double_sided
          />
        </Model>
      ) : null}

      {/* 頂部繁體中文 2D 標註列（避開 720p 上方 80px 安全區） */}
      <div
        data-allow-overlap
        style={{
          position: "absolute",
          top: 86,
          left: 40,
          padding: "12px 22px",
          borderRadius: 14,
          backgroundColor: "#1e293b",
          border: "1px solid #38bdf8",
          color: "#f8fafc",
        }}
      >
        <div style={{ fontSize: 16, color: "#38bdf8", fontWeight: 700 }}>
          {cfg.subtitle}
        </div>
        <div style={{ fontSize: 24, fontWeight: 700, marginTop: 4 }}>
          {cfg.title}
        </div>
      </div>

      {/* 底部圖例與免責聲明（避開 720p 下方 80px 安全區） */}
      <div
        data-allow-overlap
        style={{
          position: "absolute",
          bottom: 86,
          left: 40,
          right: 40,
          padding: "10px 20px",
          borderRadius: 12,
          backgroundColor: "#1e293b",
          color: "#cbd5e1",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontSize: 16,
        }}
      >
        <span>{cfg.legend}</span>
        <span>{cfg.disclaimer}</span>
      </div>
    </AbsoluteFill>
  );
}

registerRoot(() => (
  <Composition
    id="anatomy-3d"
    component={Anatomy3DTemplate}
    width={1280}
    height={720}
    fps={cfg.fps || 24}
    durationInFrames={cfg.duration_frames || 120}
  />
));
