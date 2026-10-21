import { AbsoluteFill, OffthreadVideo, interpolate, staticFile, useCurrentFrame } from "remotion";

// 來源：demo/visual/out/rhinoplasty-strut.mp4（800x512, 12fps, 26.5s）
export const FPS = 12;
export const VIDEO_W = 800;
export const VIDEO_H = 512;
export const BAND_H = 88;
export const DURATION_FRAMES = 318; // 26.5s * 12fps
export const DISCLAIMER = "一般醫學知識說明，非個人化診斷；實際狀況須由醫師當面評估。";

export const RhinoplastyStrut: React.FC = () => {
  const frame = useCurrentFrame();
  const bandOpacity = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ backgroundColor: "#0f172a" }}>
      <OffthreadVideo src={staticFile("rhinoplasty-strut.mp4")} style={{ width: VIDEO_W, height: VIDEO_H }} />
      <div
        style={{
          position: "absolute",
          left: 0,
          top: VIDEO_H,
          width: VIDEO_W,
          height: BAND_H,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          opacity: bandOpacity,
          color: "#e2e8f0",
          fontFamily: "sans-serif",
          fontSize: 20,
          letterSpacing: 1,
        }}
      >
        {DISCLAIMER}
      </div>
    </AbsoluteFill>
  );
};
