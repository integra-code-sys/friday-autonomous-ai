import QtQuick

// Componente de Cartão Holográfico Stark para Câmeras
Rectangle {
    id: card
    property string title: ""
    property string sub: ""
    property string liveBadge: "LIVE // 30 FPS"
    property color accentColor: "#ffaa18"
    property string src: ""
    property string footerL: ""
    property string footerR: ""

    color: "#d903070d"
    radius: 4
    border.color: Qt.rgba(accentColor.r, accentColor.g, accentColor.b, 0.45)
    border.width: 1
    clip: true

    // Cantoneiras em L nas 4 pontas
    Repeater {
        model: 4
        Rectangle {
            property int idx: modelData
            width: 14; height: 14; color: "transparent"
            border.width: 2; border.color: card.accentColor
            x: (idx % 2 === 0) ? 2 : parent.width - 16
            y: (idx < 2) ? 2 : parent.height - 16
            Rectangle {
                width: 10; height: 10; color: card.color
                x: (idx % 2 === 0) ? 4 : 0
                y: (idx < 2) ? 4 : 0
            }
        }
    }

    // Cabeçalho da Câmera
    Rectangle {
        id: cHead; x: 0; y: 0; width: parent.width; height: 26; color: "#e802060b"
        border.color: Qt.rgba(card.accentColor.r, card.accentColor.g, card.accentColor.b, 0.3)
        border.width: 1

        Row {
            anchors.left: parent.left; anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            Rectangle { width: 6; height: 6; radius: 3; color: "#10b981"; anchors.verticalCenter: parent.verticalCenter }
            Text { text: card.title; color: "#ffffff"; font.pixelSize: 10; font.bold: true; font.letterSpacing: 2 }
            Text { text: card.sub; color: card.accentColor; font.pixelSize: 9; font.letterSpacing: 1 }
        }

        Rectangle {
            anchors.right: parent.right; anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            width: badgeTxt.implicitWidth + 12; height: 16; radius: 2
            color: "#25ffaa18"
            border.color: card.accentColor; border.width: 1
            Text { id: badgeTxt; anchors.centerIn: parent; text: card.liveBadge; color: "#ffffff"; font.pixelSize: 8; font.bold: true; font.letterSpacing: 1 }
        }
    }

    // Vídeo ao Vivo
    Item {
        anchors { top: cHead.bottom; bottom: cFoot.top; left: parent.left; right: parent.right }
        clip: true

        Image {
            id: cImg
            anchors.fill: parent
            fillMode: Image.PreserveAspectCrop
            cache: false
            source: card.src !== "" ? card.src : ""
            property bool falhou: false
            onStatusChanged: if (status === Image.Error) { falhou = true; retryTimer.restart() }
            Timer { id: retryTimer; interval: 4000; onTriggered: cImg.falhou = false }
        }

        // Mira / Retículo HUD de Rastreamento no Centro do Feed
        Rectangle {
            anchors.centerIn: parent; width: 44; height: 44; radius: 22
            color: "transparent"; border.color: Qt.rgba(card.accentColor.r, card.accentColor.g, card.accentColor.b, 0.4); border.width: 1
            Rectangle { width: 10; height: 1; color: card.accentColor; anchors.centerIn: parent }
            Rectangle { width: 1; height: 10; color: card.accentColor; anchors.centerIn: parent }
        }
    }

    // Rodapé da Câmera
    Rectangle {
        id: cFoot; x: 0; anchors.bottom: parent.bottom; width: parent.width; height: 22; color: "#e802060b"
        border.color: Qt.rgba(card.accentColor.r, card.accentColor.g, card.accentColor.b, 0.3)
        border.width: 1

        Text {
            anchors.left: parent.left; anchors.leftMargin: 12; anchors.verticalCenter: parent.verticalCenter
            text: card.footerL; color: "#b0d0e0"; font.pixelSize: 9; font.family: "monospace"
        }
        Text {
            anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
            text: card.footerR; color: card.accentColor; font.pixelSize: 9; font.family: "monospace"
        }
    }
}
