import QtQuick
import QtQuick.Particles

// Fundo da conversa da F.R.I.D.A.Y.: preto profundo com piso holográfico em perspectiva (linhas correndo na direção de quem olha),
// poeira de nanopartículas flutuando (partículas por GPU, com profundidade) e vinheta. Piso e poeira na GPU (quase zero de CPU).
Item {
    id: fd
    property real focoX: width / 2          // ponto de fuga (o núcleo)
    property real horizonte: height * 0.64
    property real energia: 0                // 0..1 (voz): acende o piso e acelera a poeira
    property bool ativo: visible

    Rectangle { anchors.fill: parent; color: "#000000" }

    // ---------- piso em perspectiva (shader na GPU: piso.frag) ----------
    ShaderEffect {
        anchors.fill: parent
        property real tempo: 0
        property real energia: fd.energia
        property real horizonte: fd.horizonte / Math.max(1, fd.height)
        property real focoX: fd.focoX / Math.max(1, fd.width)
        property real aspecto: fd.width / Math.max(1, fd.height)
        fragmentShader: "piso.frag.qsb"
        NumberAnimation on tempo { from: 0; to: 100000; duration: 100000000; loops: Animation.Infinite; running: fd.ativo }
    }

    // ---------- poeira de nanopartículas (GPU) ----------
    ParticleSystem { id: ps; running: fd.ativo }
    ImageParticle {
        system: ps; groups: ["perto"]
        source: "qrc:///particleresources/glowdot.png"
        color: "#8fe9ff"; colorVariation: 0.08; alpha: 0.55; alphaVariation: 0.3
        entryEffect: ImageParticle.Fade
    }
    ImageParticle {
        system: ps; groups: ["longe"]
        source: "qrc:///particleresources/glowdot.png"
        color: "#5fa8ff"; alpha: 0.35; alphaVariation: 0.2
        entryEffect: ImageParticle.Fade
    }
    ImageParticle {
        system: ps; groups: ["brasa"]
        source: "qrc:///particleresources/glowdot.png"
        color: "#ff8a1f"; alpha: 0.6
        entryEffect: ImageParticle.Fade
    }
    Emitter {
        system: ps; group: "longe"; anchors.fill: parent
        emitRate: 14; lifeSpan: 12000; lifeSpanVariation: 4000; size: 4; sizeVariation: 3
        velocity: AngleDirection { angle: -90; angleVariation: 40; magnitude: 4 + fd.energia * 10; magnitudeVariation: 3 }
    }
    Emitter {
        system: ps; group: "perto"; anchors.fill: parent
        emitRate: 6; lifeSpan: 9000; lifeSpanVariation: 3000; size: 10; sizeVariation: 6
        velocity: AngleDirection { angle: -90; angleVariation: 60; magnitude: 10 + fd.energia * 25; magnitudeVariation: 6 }
    }
    Emitter {
        system: ps; group: "brasa"
        x: fd.focoX - 260; y: fd.horizonte - 40; width: 520; height: 120
        emitRate: 1.5 + fd.energia * 6; lifeSpan: 5000; size: 6; sizeVariation: 3
        velocity: AngleDirection { angle: -90; angleVariation: 25; magnitude: 22; magnitudeVariation: 10 }
    }

    // ---------- vinheta ----------
    Canvas {
        anchors.fill: parent
        onWidthChanged: requestPaint(); onHeightChanged: requestPaint()
        onPaint: {
            const c = getContext("2d"); c.reset()
            const g = c.createRadialGradient(fd.focoX, height * 0.46, height * 0.25, fd.focoX, height * 0.46, Math.max(width, height) * 0.85)
            g.addColorStop(0, "rgba(0,0,0,0)"); g.addColorStop(1, "rgba(0,0,0,0.85)")
            c.fillStyle = g; c.fillRect(0, 0, width, height)
        }
    }
}
