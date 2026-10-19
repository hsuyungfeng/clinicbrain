(function () {
  "use strict";

  const errorBox = document.getElementById("errorBox");
  const playerWrap = document.getElementById("playerWrap");
  const playerSvg = document.getElementById("playerSvg");
  const chapTitle = document.getElementById("chapTitle");
  const chapLabel = document.getElementById("chapLabel");
  const cap = document.getElementById("cap");
  const cta = document.getElementById("cta");
  const playBtn = document.getElementById("play");
  const againBtn = document.getElementById("again");
  const seekInput = document.getElementById("seek");
  const timeSpan = document.getElementById("time");
  const chapsContainer = document.getElementById("chaps");
  const mainTitle = document.getElementById("mainTitle");

  function showError() {
    if (errorBox) {
      errorBox.textContent = "無法載入";
      errorBox.style.display = "block";
    }
    if (playerWrap) {
      playerWrap.style.display = "none";
    }
  }

  const BUNDLE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._/-]*\.json$/;

  function isValidBundlePath(path) {
    if (!path || typeof path !== "string") return false;
    if (!BUNDLE_PATTERN.test(path)) return false;
    if (path.indexOf("..") !== -1) return false;
    if (path.indexOf("//") !== -1) return false;
    if (path.indexOf(":") !== -1) return false;
    if (path.indexOf("\\") !== -1) return false;
    if (path.charAt(0) === "/") return false;
    return true;
  }

  const urlParams = new URLSearchParams(window.location.search);
  const bundleParam = urlParams.get("bundle");

  if (!isValidBundlePath(bundleParam)) {
    showError();
    return;
  }

  // 僅使用 fetch 讀取同源、相對於伺服根之 bundle 路徑
  fetch("/" + bundleParam)
    .then(function (res) {
      if (!res.ok) {
        throw new Error("HTTP error");
      }
      return res.json();
    })
    .then(function (bundle) {
      if (!bundle || typeof bundle !== "object" || !Array.isArray(bundle.scenes) || bundle.scenes.length === 0) {
        showError();
        return;
      }
      initPlayer(bundle);
    })
    .catch(function () {
      showError();
    });

  function initPlayer(bundle) {
    if (mainTitle) {
      mainTitle.textContent = bundle.title || "醫學視覺解說";
    }

    if (!window.ClinicVisual || typeof window.ClinicVisual.mount !== "function") {
      showError();
      return;
    }

    const mounted = window.ClinicVisual.mount(playerSvg, bundle.scenes);
    if (!mounted) {
      showError();
      return;
    }

    const scenes = bundle.scenes;
    const totalDuration = mounted.totalDuration;
    let currentTime = 0;
    let isPlaying = false;
    let lastFrameTime = null;

    // 計算各章節起始時間
    const chapterStarts = [];
    let accTime = 0;
    for (let i = 0; i < scenes.length; i++) {
      chapterStarts.push(accTime);
      accTime += window.ClinicVisual.sceneDuration(scenes[i]);
    }

    // 建立章節按鈕
    if (chapsContainer) {
      while (chapsContainer.firstChild) {
        chapsContainer.removeChild(chapsContainer.firstChild);
      }
    }

    const chapElements = [];
    for (let i = 0; i < scenes.length; i++) {
      const btn = document.createElement("span");
      btn.className = "chap";
      btn.textContent = (i + 1) + ". " + (scenes[i].title || ("場景 " + (i + 1)));
      const startT = chapterStarts[i];
      btn.addEventListener("click", function () {
        seekTo(startT + 0.01);
      });
      if (chapsContainer) {
        chapsContainer.appendChild(btn);
      }
      chapElements.push(btn);
    }

    function formatTime(s) {
      const sec = Math.floor(Math.max(0, s));
      const m = Math.floor(sec / 60);
      const rem = sec % 60;
      return m + ":" + (rem < 10 ? "0" : "") + rem;
    }

    function updateUI() {
      mounted.renderAt(currentTime);

      const idx = mounted.sceneIndexAt(currentTime);
      const curScene = scenes[idx];

      if (chapLabel) {
        chapLabel.textContent = "章節 " + (idx + 1) + " / " + scenes.length;
      }
      if (chapTitle) {
        chapTitle.textContent = curScene ? curScene.title : "";
      }
      if (cap) {
        cap.textContent = curScene ? curScene.caption : "";
      }

      for (let i = 0; i < chapElements.length; i++) {
        if (i === idx) {
          chapElements[i].classList.add("on");
        } else {
          chapElements[i].classList.remove("on");
        }
      }

      if (seekInput) {
        const ratio = totalDuration > 0 ? currentTime / totalDuration : 0;
        seekInput.value = String(Math.round(ratio * 1000));
      }

      if (timeSpan) {
        timeSpan.textContent = formatTime(currentTime) + " / " + formatTime(totalDuration);
      }

      if (playBtn) {
        playBtn.textContent = isPlaying ? "暫停" : (currentTime >= totalDuration ? "重播" : "播放");
      }

      if (cta) {
        if (currentTime >= totalDuration - 0.05) {
          cta.classList.add("show");
        } else {
          cta.classList.remove("show");
        }
      }
    }

    function seekTo(t) {
      currentTime = Math.max(0, Math.min(totalDuration, Number(t) || 0));
      updateUI();
    }

    function animationLoop(timestamp) {
      if (!isPlaying) return;
      if (lastFrameTime === null) {
        lastFrameTime = timestamp;
      }
      const dt = (timestamp - lastFrameTime) / 1000;
      lastFrameTime = timestamp;

      currentTime = Math.min(totalDuration, currentTime + dt);
      updateUI();

      if (currentTime >= totalDuration) {
        isPlaying = false;
        lastFrameTime = null;
        updateUI();
        return;
      }

      window.requestAnimationFrame(animationLoop);
    }

    function startPlayback() {
      if (currentTime >= totalDuration) {
        currentTime = 0;
      }
      isPlaying = true;
      lastFrameTime = null;
      window.requestAnimationFrame(animationLoop);
      updateUI();
    }

    function pausePlayback() {
      isPlaying = false;
      lastFrameTime = null;
      updateUI();
    }

    if (playBtn) {
      playBtn.addEventListener("click", function () {
        if (isPlaying) {
          pausePlayback();
        } else {
          startPlayback();
        }
      });
    }

    if (againBtn) {
      againBtn.addEventListener("click", function () {
        currentTime = 0;
        startPlayback();
      });
    }

    if (seekInput) {
      seekInput.addEventListener("input", function () {
        const val = Number(seekInput.value) || 0;
        seekTo((val / 1000) * totalDuration);
      });
    }

    // 暴露全域控制介面供測試與影片錄製使用
    window.__player = {
      seek: seekTo,
      total: totalDuration,
      ready: true
    };

    updateUI();
  }
})();
