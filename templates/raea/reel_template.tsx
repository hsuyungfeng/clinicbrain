import {
  AbsoluteFill,
  Audio,
  Composition,
  Mix,
  Sequence,
  Video,
  interpolate,
  registerRoot,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "raea";
import config from "./reel_config.json";

const FONT_TC = "'Noto Sans CJK TC', 'Noto Sans TC', sans-serif";

function ClinicReelTemplate() {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const headerY = interpolate(
    spring({ frame, fps, config: { damping: 16, stiffness: 120 } }),
    [0, 1],
    [-40, 0]
  );
  const headerOpacity = interpolate(frame, [0, 15], [0, 1], {
    extrapolateRight: "clamp",
  });

  const ctaStart = Math.max(0, durationInFrames - Math.round(fps * 3.5));
  const ctaOpacity = interpolate(frame, [ctaStart, ctaStart + 18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // 依 3 幕進度輪播口白重點字幕
  const lines: string[] = Array.isArray(config.narration_lines) ? config.narration_lines : [];
  const lineIdx = lines.length > 0
    ? Math.min(lines.length - 1, Math.floor((frame / Math.max(1, durationInFrames)) * lines.length))
    : 0;
  const activeLine = lines[lineIdx] || "";

  return (
    <AbsoluteFill style={{ backgroundColor: "#0f172a", fontFamily: FONT_TC }}>
      <Mix lufs={-14} ceiling={-1}>
        <Audio
          src={staticFile(config.audio_file)}
          volume={0.35}
          fadeIn={12}
          fadeOut={24}
        />
      </Mix>

      {/* 頂部：對稱置中品牌與主題字卡（避開上 220px 與左右 140px 安全區） */}
      <div
        style={{
          position: "absolute",
          top: 225,
          left: 145,
          right: 145,
          opacity: headerOpacity,
          transform: `translateY(${headerY}px)`,
          display: "flex",
          flexDirection: "column",
          gap: 10,
          padding: "20px 24px",
          borderRadius: 22,
          backgroundColor: "rgba(15, 23, 42, 0.9)",
          border: "2px solid rgba(56, 189, 248, 0.45)",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span style={{ color: "#38bdf8", fontSize: 24, fontWeight: 700 }}>
            {config.clinic_name} · 衛教動畫
          </span>
          <span
            style={{
              color: "#e2e8f0",
              backgroundColor: "rgba(43, 108, 176, 0.75)",
              padding: "4px 14px",
              borderRadius: 999,
              fontSize: 18,
              fontWeight: 600,
            }}
          >
            {config.badge}
          </span>
        </div>
        <div
          style={{
            color: "#f8fafc",
            fontSize: 34,
            fontWeight: 700,
            lineHeight: 1.3,
          }}
        >
          {config.hook_title}
        </div>
      </div>

      {/* 中央：既有 ClinicBrain 醫學動畫視窗 */}
      <div
        style={{
          position: "absolute",
          top: 415,
          left: 0,
          right: 0,
          height: 790,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
        }}
      >
        <Video
          src={staticFile(config.video_file)}
          startFrom={0}
          endAt={durationInFrames}
          muted
          style={{ width: "100%", height: "100%", objectFit: "contain" }}
        />
      </div>

      {/* 中下：Ornith 口白重點字幕條（避開右側 140px 按鈕區） */}
      {activeLine ? (
        <div
          style={{
            position: "absolute",
            bottom: 615,
            left: 145,
            right: 145,
            padding: "14px 20px",
            borderRadius: 16,
            backgroundColor: "rgba(30, 41, 59, 0.92)",
            border: "1px solid rgba(148, 163, 184, 0.35)",
            color: "#f1f5f9",
            fontSize: 22,
            lineHeight: 1.4,
            textAlign: "center",
          }}
        >
          {activeLine}
        </div>
      ) : null}

      {/* 結尾預約 CTA（最後 3.5 秒淡入，對稱置中） */}
      <Sequence from={ctaStart} durationInFrames={durationInFrames - ctaStart}>
        <div
          style={{
            position: "absolute",
            bottom: 525,
            left: 145,
            right: 145,
            opacity: ctaOpacity,
            padding: "16px 24px",
            borderRadius: 18,
            backgroundColor: "rgba(47, 158, 107, 0.94)",
            color: "#ffffff",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span style={{ fontSize: 26, fontWeight: 700 }}>{config.cta_text}</span>
          <span style={{ fontSize: 28, fontWeight: 700 }}>{config.clinic_phone}</span>
        </div>
      </Sequence>

      {/* 底部：醫療法規免責聲明（對稱置中、避開下 420px 安全區） */}
      <div
        style={{
          position: "absolute",
          bottom: 425,
          left: 145,
          right: 145,
          padding: "14px 20px",
          borderRadius: 16,
          backgroundColor: "rgba(15, 23, 42, 0.9)",
          color: "#cbd5e1",
          fontSize: 20,
          lineHeight: 1.4,
          textAlign: "center",
        }}
      >
        {config.disclaimer}
      </div>
    </AbsoluteFill>
  );
}

registerRoot(() => (
  <Composition
    id="clinic-reel-batch"
    component={ClinicReelTemplate}
    width={1080}
    height={1920}
    fps={config.fps}
    durationInFrames={config.duration_frames}
  />
));
