import { Composition } from "remotion";
import { RhinoplastyStrut, DURATION_FRAMES, FPS, VIDEO_W, VIDEO_H, BAND_H } from "./Composition";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="RhinoplastyStrut"
      component={RhinoplastyStrut}
      durationInFrames={DURATION_FRAMES}
      fps={FPS}
      width={VIDEO_W}
      height={VIDEO_H + BAND_H}
    />
  );
};
