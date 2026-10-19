import QtQuick
import Quickshell
// teste offline do fundo: renderiza 1920x1080 e salva /tmp/painel_test.png  (timeout 20 qs -p painel_test.qml)
ShellRoot {
    FloatingWindow {
        implicitWidth: 1920; implicitHeight: 1080; color: "black"
        PainelStark { id: pn; width: 1920; height: 1080; scale: Math.min(parent.width / 1920, parent.height / 1080); transformOrigin: Item.TopLeft; online: true; cpu: 37; ram: 62; gpu: 28; vram: 71; temp: 64; clock: "21:40:12"; date: "QUI, 15 OUT"
            pessoas: 1; listaPessoas: [{nome: "Iann"}]; objetos: 2; listaObjetos: ["celular", "copo"]; natOnline: true; usbOnline: true; ptzOnline: true; mode: "speaking"; level: 0.6 }
        Timer { interval: 4500; running: true; onTriggered: pn.grabToImage(r => { r.saveToFile("/tmp/painel_test.png"); Qt.quit() }) }
    }
}
