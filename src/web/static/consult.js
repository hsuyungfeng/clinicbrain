(function() {
    var POLL_INTERVAL_MS = 2500;
    var POLL_MAX_MS = 240000;
    var SVG_NS = "http://www.w3.org/2000/svg";
    var VISUAL_FIXED_DISCLAIMER = "一般醫學知識說明，非個人化診斷；實際狀況須由醫師當面評估";

    var consultInput = document.getElementById("consultInput");
    var charCounter = document.getElementById("charCounter");
    var btnSubmit = document.getElementById("btnSubmit");
    var loadingMessage = document.getElementById("loadingMessage");
    var errorMessage = document.getElementById("errorMessage");
    var resultArea = document.getElementById("resultArea");
    var statusBadge = document.getElementById("statusBadge");
    var resultLabel = document.getElementById("resultLabel");
    var resultMessage = document.getElementById("resultMessage");
    var resultDisclaimer = document.getElementById("resultDisclaimer");
    var bookingContainer = document.getElementById("bookingContainer");
    var bookingLink = document.getElementById("bookingLink");
    var visualCard = document.getElementById("visualCard");

    consultInput.addEventListener("input", function() {
        var len = consultInput.value ? consultInput.value.length : 0;
        charCounter.textContent = len + "/300";
    });

    consultInput.addEventListener("keydown", function(e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleConsultSubmit();
        }
    });

    btnSubmit.addEventListener("click", function() {
        handleConsultSubmit();
    });

    function clearElement(el) {
        while (el && el.firstChild) {
            el.removeChild(el.firstChild);
        }
    }

    function hideVisualCard() {
        if (!visualCard) {
            return;
        }
        visualCard.style.display = "none";
        clearElement(visualCard);
    }

    function postVisualEvent(topicKey, eventName) {
        if (!topicKey || !eventName) {
            return;
        }
        try {
            fetch("/api/v1/general/visual/event", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    topic_key: String(topicKey),
                    event: String(eventName)
                }),
                keepalive: true
            }).catch(function() {});
        } catch (err) {}
    }

    function tonePalette(tone) {
        if (tone === "warning") {
            return { fill: "#feebc8", stroke: "#dd6b20", text: "#7b341e" };
        }
        if (tone === "optimal") {
            return { fill: "#c6f6d5", stroke: "#38a169", text: "#22543d" };
        }
        return { fill: "#edf2f7", stroke: "#a0aec0", text: "#2d3748" };
    }

    function createSvgNode(tag, attrs) {
        var node = document.createElementNS(SVG_NS, tag);
        if (attrs) {
            for (var k in attrs) {
                if (Object.prototype.hasOwnProperty.call(attrs, k)) {
                    node.setAttribute(k, String(attrs[k]));
                }
            }
        }
        return node;
    }

    function buildBlueprintSvg(scene) {
        var bp = scene && scene.blueprint ? String(scene.blueprint) : "";
        if (bp !== "process_diagram" && bp !== "contrast" && bp !== "timeline") {
            return null;
        }

        var rawLabels = Array.isArray(scene.labels) ? scene.labels.slice(0, 4) : [];
        var items = rawLabels.length > 0 ? rawLabels : [{ text: scene.title || "", tone: "neutral" }];
        var count = items.length;
        var svg = createSvgNode("svg", {
            viewBox: "0 0 480 120",
            "class": "visual-svg",
            role: "img",
            "aria-label": scene.title || "圖解說明"
        });

        if (bp === "process_diagram") {
            var stepGap = 480 / (count + 1);
            for (var i = 0; i < count; i++) {
                var cx = Math.round(stepGap * (i + 1));
                var cy = 54;
                var pal = tonePalette(items[i].tone);

                if (i < count - 1) {
                    var nextCx = Math.round(stepGap * (i + 2));
                    var line = createSvgNode("line", {
                        x1: cx + 28,
                        y1: cy,
                        x2: nextCx - 28,
                        y2: cy,
                        stroke: "#a0aec0",
                        "stroke-width": 2
                    });
                    svg.appendChild(line);

                    var arrow = createSvgNode("polygon", {
                        points: (nextCx - 28) + "," + cy + " " + (nextCx - 35) + "," + (cy - 4) + " " + (nextCx - 35) + "," + (cy + 4),
                        fill: "#a0aec0"
                    });
                    svg.appendChild(arrow);
                }

                var circle = createSvgNode("circle", {
                    cx: cx,
                    cy: cy,
                    r: 24,
                    fill: pal.fill,
                    stroke: pal.stroke,
                    "stroke-width": 2
                });
                svg.appendChild(circle);

                var numText = createSvgNode("text", {
                    x: cx,
                    y: cy + 5,
                    "text-anchor": "middle",
                    fill: pal.text,
                    "font-size": "13",
                    "font-weight": "bold"
                });
                numText.textContent = String(i + 1);
                svg.appendChild(numText);

                var lbText = createSvgNode("text", {
                    x: cx,
                    y: 98,
                    "text-anchor": "middle",
                    fill: "#2d3748",
                    "font-size": "12"
                });
                lbText.textContent = String(items[i].text || "");
                svg.appendChild(lbText);
            }
        } else if (bp === "contrast") {
            var leftItems = [];
            var rightItems = [];
            for (var j = 0; j < count; j++) {
                if (j % 2 === 0) {
                    leftItems.push(items[j]);
                } else {
                    rightItems.push(items[j]);
                }
            }
            if (rightItems.length === 0 && leftItems.length > 0) {
                rightItems.push(leftItems[0]);
            }

            var leftPal = tonePalette(leftItems[0] ? leftItems[0].tone : "neutral");
            var rightPal = tonePalette(rightItems[0] ? rightItems[0].tone : "optimal");

            var rectL = createSvgNode("rect", {
                x: 20,
                y: 16,
                width: 205,
                height: 88,
                rx: 8,
                fill: leftPal.fill,
                stroke: leftPal.stroke,
                "stroke-width": 2
            });
            svg.appendChild(rectL);

            var rectR = createSvgNode("rect", {
                x: 255,
                y: 16,
                width: 205,
                height: 88,
                rx: 8,
                fill: rightPal.fill,
                stroke: rightPal.stroke,
                "stroke-width": 2
            });
            svg.appendChild(rectR);

            for (var li = 0; li < leftItems.length; li++) {
                var tL = createSvgNode("text", {
                    x: 122,
                    y: leftItems.length > 1 ? (48 + li * 26) : 64,
                    "text-anchor": "middle",
                    fill: leftPal.text,
                    "font-size": "13",
                    "font-weight": "bold"
                });
                tL.textContent = String(leftItems[li].text || "");
                svg.appendChild(tL);
            }

            for (var ri = 0; ri < rightItems.length; ri++) {
                var tR = createSvgNode("text", {
                    x: 357,
                    y: rightItems.length > 1 ? (48 + ri * 26) : 64,
                    "text-anchor": "middle",
                    fill: rightPal.text,
                    "font-size": "13",
                    "font-weight": "bold"
                });
                tR.textContent = String(rightItems[ri].text || "");
                svg.appendChild(tR);
            }
        } else if (bp === "timeline") {
            var baseLine = createSvgNode("line", {
                x1: 48,
                y1: 52,
                x2: 432,
                y2: 52,
                stroke: "#cbd5e0",
                "stroke-width": 4
            });
            svg.appendChild(baseLine);

            for (var ti = 0; ti < count; ti++) {
                var tx = count === 1 ? 240 : Math.round(64 + (352 * ti) / (count - 1));
                var tpal = tonePalette(items[ti].tone);

                var nodeCircle = createSvgNode("circle", {
                    cx: tx,
                    cy: 52,
                    r: 12,
                    fill: tpal.fill,
                    stroke: tpal.stroke,
                    "stroke-width": 3
                });
                svg.appendChild(nodeCircle);

                var tLabel = createSvgNode("text", {
                    x: tx,
                    y: 90,
                    "text-anchor": "middle",
                    fill: "#2d3748",
                    "font-size": "12",
                    "font-weight": "bold"
                });
                tLabel.textContent = String(items[ti].text || "");
                svg.appendChild(tLabel);
            }
        }

        return svg;
    }

    function renderVisual(data) {
        hideVisualCard();
        if (!data || !visualCard) {
            return;
        }
        var status = data.status || "";
        if (status !== "answered" && status !== "llm_general") {
            return;
        }
        var vis = data.visual;
        if (!vis || typeof vis !== "object") {
            return;
        }
        var scenes = vis.scenes;
        if (!Array.isArray(scenes) || scenes.length < 3 || scenes.length > 5) {
            return;
        }

        var topicKey = vis.topic_key ? String(vis.topic_key) : "";
        var currentIndex = 0;
        var shownSent = false;
        var completedSent = false;

        var headerEl = document.createElement("div");
        headerEl.className = "visual-header";

        var titleEl = document.createElement("div");
        titleEl.className = "visual-title";
        titleEl.textContent = vis.title ? String(vis.title) : "醫學圖解說明";

        var stepIndicator = document.createElement("span");
        stepIndicator.className = "visual-step-indicator";

        headerEl.appendChild(titleEl);
        headerEl.appendChild(stepIndicator);

        var sceneBox = document.createElement("div");
        sceneBox.className = "visual-scene-box";

        var sceneTitle = document.createElement("div");
        sceneTitle.className = "visual-scene-title";

        var svgWrap = document.createElement("div");
        svgWrap.className = "visual-svg-wrap";

        var sceneCaption = document.createElement("div");
        sceneCaption.className = "visual-scene-caption";

        var labelsWrap = document.createElement("div");
        labelsWrap.className = "visual-labels";

        sceneBox.appendChild(sceneTitle);
        sceneBox.appendChild(svgWrap);
        sceneBox.appendChild(sceneCaption);
        sceneBox.appendChild(labelsWrap);

        var controlsEl = document.createElement("div");
        controlsEl.className = "visual-controls";

        var btnPrev = document.createElement("button");
        btnPrev.type = "button";
        btnPrev.className = "btn-visual-nav";
        btnPrev.textContent = "上一步";

        var dotsWrap = document.createElement("div");
        dotsWrap.className = "visual-dots";
        var dotNodes = [];
        for (var d = 0; d < scenes.length; d++) {
            var dot = document.createElement("span");
            dot.className = "visual-dot";
            dotsWrap.appendChild(dot);
            dotNodes.push(dot);
        }

        var btnNext = document.createElement("button");
        btnNext.type = "button";
        btnNext.className = "btn-visual-nav";
        btnNext.textContent = "下一步";

        controlsEl.appendChild(btnPrev);
        controlsEl.appendChild(dotsWrap);
        controlsEl.appendChild(btnNext);

        var disclaimerEl = document.createElement("div");
        disclaimerEl.className = "visual-disclaimer";
        disclaimerEl.textContent = VISUAL_FIXED_DISCLAIMER;

        visualCard.appendChild(headerEl);
        visualCard.appendChild(sceneBox);
        visualCard.appendChild(controlsEl);
        visualCard.appendChild(disclaimerEl);

        function updateSceneView() {
            var sc = scenes[currentIndex] || {};
            stepIndicator.textContent = (currentIndex + 1) + " / " + scenes.length;
            sceneTitle.textContent = sc.title ? String(sc.title) : "";
            sceneCaption.textContent = sc.caption ? String(sc.caption) : "";

            clearElement(svgWrap);
            var svgNode = buildBlueprintSvg(sc);
            if (svgNode) {
                svgWrap.appendChild(svgNode);
                svgWrap.style.display = "flex";
            } else {
                svgWrap.style.display = "none";
            }

            clearElement(labelsWrap);
            var lbs = Array.isArray(sc.labels) ? sc.labels : [];
            for (var k = 0; k < lbs.length; k++) {
                var lb = lbs[k];
                if (!lb || typeof lb !== "object") {
                    continue;
                }
                var chip = document.createElement("span");
                var tone = lb.tone === "warning" || lb.tone === "optimal" ? lb.tone : "neutral";
                chip.className = "visual-chip tone-" + tone;
                chip.textContent = lb.text ? String(lb.text) : "";
                labelsWrap.appendChild(chip);
            }

            for (var m = 0; m < dotNodes.length; m++) {
                if (m === currentIndex) {
                    dotNodes[m].className = "visual-dot visual-dot-active";
                } else {
                    dotNodes[m].className = "visual-dot";
                }
            }

            btnPrev.disabled = currentIndex <= 0;
            btnNext.disabled = currentIndex >= scenes.length - 1;

            if (!completedSent && currentIndex === scenes.length - 1) {
                completedSent = true;
                postVisualEvent(topicKey, "completed");
            }
        }

        btnPrev.addEventListener("click", function() {
            if (currentIndex > 0) {
                currentIndex -= 1;
                updateSceneView();
            }
        });

        btnNext.addEventListener("click", function() {
            if (currentIndex < scenes.length - 1) {
                currentIndex += 1;
                updateSceneView();
            }
        });

        updateSceneView();
        visualCard.style.display = "block";

        if (!shownSent) {
            shownSent = true;
            postVisualEvent(topicKey, "shown");
        }
    }

    function handleConsultSubmit() {
        var q = consultInput.value ? consultInput.value.trim() : "";
        if (!q) {
            return;
        }

        consultInput.value = "";
        charCounter.textContent = "0/300";
        consultInput.disabled = true;
        btnSubmit.disabled = true;

        resultArea.style.display = "none";
        hideVisualCard();
        errorMessage.style.display = "none";
        loadingMessage.style.display = "block";
        loadingMessage.textContent = "整理中，通常需 20 秒至 2 分鐘，請稍候";

        fetch("/api/v1/general/consult/jobs", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ query: q })
        })
        .then(function(res) {
            if (!res.ok) {
                throw new Error("HTTP " + res.status);
            }
            return res.json();
        })
        .then(function(data) {
            if (data && data.job_id) {
                var startTime = Date.now();
                pollJob(data.job_id, startTime);
            } else {
                loadingMessage.style.display = "none";
                consultInput.disabled = false;
                btnSubmit.disabled = false;
                renderResult(data);
            }
        })
        .catch(function() {
            loadingMessage.style.display = "none";
            consultInput.disabled = false;
            btnSubmit.disabled = false;
            errorMessage.textContent = "連線失敗或網路異常，請稍後再試。";
            errorMessage.style.display = "block";
        });
    }

    function pollJob(jobId, startTime) {
        if (Date.now() - startTime > POLL_MAX_MS) {
            loadingMessage.style.display = "none";
            consultInput.disabled = false;
            btnSubmit.disabled = false;
            errorMessage.textContent = "整理逾時，請稍後再試。";
            errorMessage.style.display = "block";
            return;
        }

        fetch("/api/v1/general/consult/jobs/" + encodeURIComponent(jobId))
        .then(function(res) {
            if (res.status === 404) {
                loadingMessage.style.display = "none";
                consultInput.disabled = false;
                btnSubmit.disabled = false;
                errorMessage.textContent = "結果已過期，請重新送出";
                errorMessage.style.display = "block";
                return null;
            }
            if (!res.ok) {
                throw new Error("HTTP " + res.status);
            }
            return res.json();
        })
        .then(function(data) {
            if (!data) {
                return;
            }
            if (data.status === "pending") {
                setTimeout(function() {
                    pollJob(jobId, startTime);
                }, POLL_INTERVAL_MS);
            } else {
                loadingMessage.style.display = "none";
                consultInput.disabled = false;
                btnSubmit.disabled = false;
                renderResult(data);
            }
        })
        .catch(function() {
            loadingMessage.style.display = "none";
            consultInput.disabled = false;
            btnSubmit.disabled = false;
            errorMessage.textContent = "連線失敗或網路異常，請稍後再試。";
            errorMessage.style.display = "block";
        });
    }

    function renderResult(data) {
        resultArea.className = "result-card";
        var status = data.status || "";

        if (status === "red_flag") {
            resultArea.classList.add("status-red-flag");
            statusBadge.textContent = "緊急就醫指示";
        } else if (status === "answered") {
            resultArea.classList.add("status-answered");
            statusBadge.textContent = "衛教諮詢說明";
        } else if (status === "llm_general") {
            resultArea.classList.add("status-llm-general");
            statusBadge.textContent = "一般醫學說明";
        } else if (status === "busy") {
            resultArea.classList.add("status-busy");
            statusBadge.textContent = "系統忙碌";
        } else {
            resultArea.classList.add("status-no-match");
            statusBadge.textContent = "諮詢回覆";
        }

        resultMessage.textContent = data.message || "";

        if (data.label) {
            resultLabel.textContent = data.label;
            resultLabel.style.display = "block";
        } else {
            resultLabel.textContent = "";
            resultLabel.style.display = "none";
        }

        if (data.disclaimer) {
            resultDisclaimer.textContent = data.disclaimer;
            resultDisclaimer.style.display = "block";
        } else {
            resultDisclaimer.textContent = "";
            resultDisclaimer.style.display = "none";
        }

        var url = data.booking_url || "https://doctor-toolbox.com/";
        bookingLink.setAttribute("href", url);
        bookingContainer.style.display = "block";

        resultArea.style.display = "block";
        renderVisual(data);
    }
})();
