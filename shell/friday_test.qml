import QtQuick
Rectangle {
    width: 384; height: 1080; color: "#02060c"
    property string pose: "neutro"
    FridayBody { anchors.fill: parent; pose: parent.pose }
}
