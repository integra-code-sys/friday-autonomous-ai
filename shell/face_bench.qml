import QtQuick
Item {
    id: fc
    width: 1280; height: 720
    property real mouth: 0; property real smile: 0; property real browL: 0; property real browR: 0
    property real blink: 0; property real cheek: 0; property real lookX: 0; property real lookY: 0
    property real brist: 0; property real yaw: 0; property real pitch: 0; property real roll: 0
    property real lipW: 0; property real tm: 3.0
    property real armLs: 0.1; property real armLa: 0.06; property real armLe: 0.15
    property real armRs: 0.1; property real armRa: 0.06; property real armRe: 0.15
    property real lean: 0; property real sway: 0; property real twist: 0
    property real armLr: 0; property real armRr: 0; property real shrugL: 0; property real shrugR: 0
    property vector4d lFc: Qt.vector4d(0,0,0,0); property vector4d lSp: Qt.vector4d(0,0,0,0); property vector4d lWr: Qt.vector4d(0,0,0,0)
    property vector4d rFc: Qt.vector4d(0,0,0,0); property vector4d rSp: Qt.vector4d(0,0,0,0); property vector4d rWr: Qt.vector4d(0,0,0,0)
    property real aspectR: width / Math.max(1, height)
    property real sceneW: 960
    property real mx: 0.0; property real my: 0.0; property real mon: 0.0
    Image { id: headImg; source: "head.png"; visible: false; smooth: true }
    Image { id: volHead; source: "assets/head.png"; visible: false; smooth: true }
    Image { id: volNeck; source: "assets/neck.png"; visible: false; smooth: true }
    Image { id: volBust; source: "assets/bust.png"; visible: false; smooth: true }
    Image { id: volArmLu; source: "assets/armLu.png"; visible: false; smooth: true }
    Image { id: volEye; source: "assets/eye.png"; visible: false; smooth: true }
    Image { id: volHand; source: "assets/hand_rig.png"; visible: false; smooth: true }
    Image { id: volArmRu; source: "assets/armRu.png"; visible: false; smooth: true }
    Image { id: texWeave; source: "assets/tex_weave.jpg"; visible: false; smooth: true; mipmap: true }
    Image { id: texPlates; source: "assets/tex_plates.jpg"; visible: false; smooth: true; mipmap: true }
    ShaderEffect {
        id: scene3d
        width: fc.sceneW; height: Math.max(1, Math.round(fc.sceneW / fc.aspectR))
        property real time: fc.tm
        property real aspect: fc.aspectR
        property real mouth: fc.mouth
        property real smile: fc.smile
        property real browL: fc.browL
        property real browR: fc.browR
        property real blink: fc.blink
        property real cheek: fc.cheek
        property real lookX: fc.lookX
        property real lookY: fc.lookY
        property real brist: fc.brist
        property real yaw: fc.yaw
        property real pitch: fc.pitch
        property real roll: fc.roll
        property real lipW: fc.lipW
        property variant tHead: volHead
        property variant tNeck: volNeck
        property variant tBust: volBust
        property variant tArmLu: volArmLu
        property variant tEye: volEye
        property variant tHand: volHand
        property variant tArmRu: volArmRu
        property real armLs: fc.armLs
        property real armLa: fc.armLa
        property real armLe: fc.armLe
        property real armRs: fc.armRs
        property real armRa: fc.armRa
        property real armRe: fc.armRe
        property real lean: fc.lean
        property real sway: fc.sway
        property real twist: fc.twist
        property real armLr: fc.armLr
        property real armRr: fc.armRr
        property real shrugL: fc.shrugL
        property real shrugR: fc.shrugR
        property vector4d lFc: fc.lFc
        property vector4d lSp: fc.lSp
        property vector4d lWr: fc.lWr
        property vector4d rFc: fc.rFc
        property vector4d rSp: fc.rSp
        property vector4d rWr: fc.rWr
        property variant tWeave: texWeave
        property variant tPlates: texPlates
        fragmentShader: "scene3d.frag.qsb"
    }
    ShaderEffectSource { id: sceneTex; sourceItem: scene3d; hideSource: true; live: true; smooth: true
                         textureSize: Qt.size(scene3d.width, scene3d.height) }
    ShaderEffect {
        anchors.fill: parent
        property real time: fc.tm
        property real aspect: fc.aspectR
        property real glow: 0.6
        property vector2d mouse: Qt.vector2d(fc.mx, fc.my)
        property real mouseOn: fc.mon
        property variant scene: sceneTex
        property variant tex: headImg
        fragmentShader: "face.frag.qsb"
    }
}
