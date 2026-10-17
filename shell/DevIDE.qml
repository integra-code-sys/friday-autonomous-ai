import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// MODO DEV · Claude CLI — painel tipo IDE: árvore de arquivos, visualizador de código/diff,
// conversa com o Claude (stream-json) e terminal. Fala com o daemon via {"type":"ide","op":...}.
Item {
    id: ide

    // ---- entradas (preenchidas pelo shell.qml) ----
    property bool online: false
    property var estado: null          // último ide_estado
    property var arvore: null          // último ide_arvore
    property var arquivo: null         // último ide_arquivo
    property var diffAtual: null       // último ide_diff
    property var eventos: null         // ListModel com ide_ev achatados (strings)

    // ---- saídas ----
    signal enviarCmd(var obj)
    signal fechar()

    // ---- estado interno ----
    readonly property bool rodando: !!(estado && estado.rodando)
    readonly property string modeloAtual: (estado && estado.modelo) ? String(estado.modelo) : "sonnet"
    readonly property real custoTotal: (estado && estado.custo_total) ? Number(estado.custo_total) : 0
    property int abaAtual: -1
    property bool mostrarDiff: false
    property bool termAberto: true
    property var diffs: ({})           // rel -> diff unified
    property int processados: 0        // eventos já varridos em busca de "edicao"

    readonly property color cCiano: "#7fe6ff"
    readonly property color cLaranja: "#ff8a1f"
    readonly property color cTexto: "#dceefb"
    readonly property color cSuave: "#9fb4c8"
    readonly property color cFundo: "#e6050b12"
    readonly property color cBorda: "#557fe6ff"
    readonly property color cVerde: "#7fffb0"
    readonly property color cVermelho: "#ff7f9f"
    readonly property color cRoxo: "#c99bff"

    ListModel { id: abas }             // rel, texto, linhas, truncado

    function cmd(op, extra) {
        const o = { type: "ide", op: op }
        if (extra) for (const k in extra) o[k] = extra[k]
        ide.enviarCmd(o)
    }
    function pedirTudo() {
        cmd("estado")
        cmd("arvore", { rel: (arvore && arvore.rel) ? arvore.rel : "" })
    }
    function abrirArquivo(rel) {
        if (!rel) return
        cmd("ler", { rel: rel })
        cmd("diff", { rel: rel })
    }
    function guardarDiff(rel, d) {
        if (!rel) return
        const n = Object.assign({}, diffs)
        n[rel] = d || ""
        diffs = n
    }
    function diffDe(rel) { return (rel && diffs[rel]) ? diffs[rel] : "" }
    function relAba() { return (abaAtual >= 0 && abaAtual < abas.count) ? abas.get(abaAtual).rel : "" }
    function nomeBase(rel) { const p = String(rel || "").split("/"); return p[p.length - 1] || rel }
    function pai(rel) {
        const p = String(rel || "").split("/").filter(s => s !== "")
        p.pop()
        return p.join("/")
    }
    function numeros(n) {
        let s = ""
        for (let i = 1; i <= n; i++) s += (i > 1 ? "\n" : "") + i
        return s
    }
    function sincronizarCombos() {
        if (!estado) return
        const ps = estado.projetos || []
        for (let i = 0; i < ps.length; i++) {
            if (ps[i].caminho === estado.projeto || ps[i].nome === estado.projeto) { cbProjeto.currentIndex = i; break }
        }
        const mi = ["sonnet", "opus", "haiku"].indexOf(modeloAtual)
        if (mi >= 0) cbModelo.currentIndex = mi
    }
    function varrerEventos() {
        if (!eventos) { processados = 0; return }
        if (eventos.count < processados) processados = 0
        for (let i = processados; i < eventos.count; i++) {
            const e = eventos.get(i)
            if (e.kind === "edicao" && e.arquivo) guardarDiff(e.arquivo, e.diff)
        }
        processados = eventos.count
    }
    function enviar() {
        const t = entrada.text.trim()
        if (t === "" || rodando || !online) return
        cmd("enviar", { texto: t })
        entrada.text = ""
    }

    onEstadoChanged: sincronizarCombos()
    onArquivoChanged: {
        if (!arquivo || !arquivo.rel) return
        const dados = { rel: String(arquivo.rel), texto: String(arquivo.texto || ""),
                        linhas: Number(arquivo.linhas || 0), truncado: !!arquivo.truncado }
        for (let i = 0; i < abas.count; i++) {
            if (abas.get(i).rel === dados.rel) { abas.set(i, dados); abaAtual = i; return }
        }
        if (abas.count >= 8) { abas.remove(0); if (abaAtual > 0) abaAtual-- }
        abas.append(dados)
        abaAtual = abas.count - 1
        mostrarDiff = false
    }
    onDiffAtualChanged: if (diffAtual && diffAtual.rel) guardarDiff(String(diffAtual.rel), String(diffAtual.diff || ""))
    onEventosChanged: { processados = 0; varrerEventos() }
    onVisibleChanged: if (visible) pedirTudo()
    Component.onCompleted: { varrerEventos(); pedirTudo() }

    Connections {
        target: ide.eventos
        ignoreUnknownSignals: true
        function onCountChanged() { ide.varrerEventos() }
    }

    // ---- componentes reaproveitados ----
    component BotaoIde: Rectangle {
        id: bti
        property string rotulo: ""
        property bool ativo: true
        property color corBorda: "#447fe6ff"
        signal clicado()
        implicitWidth: bTxt.implicitWidth + 18
        implicitHeight: 26
        radius: 5
        opacity: ativo ? 1 : 0.4
        color: bMa.containsMouse && ativo ? "#227fe6ff" : "transparent"
        border.color: corBorda
        Text { id: bTxt; anchors.centerIn: parent; text: bti.rotulo; color: "#cfefff"; font.pixelSize: 11 }
        MouseArea { id: bMa; anchors.fill: parent; hoverEnabled: true; enabled: bti.ativo; onClicked: bti.clicado() }
    }

    component DiffLinhas: Column {
        id: dl
        property string diff: ""
        property int maxLinhas: 100000
        readonly property var linhas: diff === "" ? [] : diff.split("\n").slice(0, maxLinhas)
        spacing: 0
        Repeater {
            model: dl.linhas
            Rectangle {
                required property string modelData
                readonly property string c0: modelData.length ? modelData.charAt(0) : ""
                readonly property bool cab: modelData.startsWith("+++") || modelData.startsWith("---")
                width: dl.width
                height: lt.implicitHeight
                color: cab ? "transparent" : (c0 === "+" ? "#1a7fffb0" : (c0 === "-" ? "#1aff7f9f" : "transparent"))
                Text {
                    id: lt
                    width: parent.width
                    text: parent.modelData === "" ? " " : parent.modelData
                    textFormat: Text.PlainText
                    font.family: "monospace"; font.pixelSize: 12
                    wrapMode: Text.WrapAnywhere
                    color: parent.cab ? "#9fb4c8"
                         : parent.modelData.startsWith("@@") ? "#7fe6ff"
                         : parent.c0 === "+" ? "#7fffb0"
                         : parent.c0 === "-" ? "#ff7f9f" : "#c8d6e2"
                }
            }
        }
    }

    Rectangle { anchors.fill: parent; color: ide.cFundo; border.color: ide.cBorda; border.width: 1; radius: 10 }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        // ================= BARRA SUPERIOR =================
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Text { text: "MODO DEV · Claude CLI"; color: ide.cLaranja; font.pixelSize: 17; font.bold: true; font.letterSpacing: 2 }
            Rectangle { width: 9; height: 9; radius: 5; color: ide.online ? ide.cVerde : ide.cVermelho }
            ComboBox {
                id: cbProjeto
                Layout.preferredWidth: 240
                model: (ide.estado && ide.estado.projetos) ? ide.estado.projetos : []
                textRole: "nome"
                enabled: !ide.rodando
                onModelChanged: Qt.callLater(ide.sincronizarCombos)
                onActivated: idx => {
                    const p = (ide.estado && ide.estado.projetos) ? ide.estado.projetos[idx] : null
                    if (p) { abas.clear(); ide.abaAtual = -1; ide.diffs = ({}); ide.cmd("abrir_projeto", { caminho: p.caminho }) }
                }
            }
            Row {
                spacing: 6
                Rectangle {
                    id: pulso
                    width: 10; height: 10; radius: 5
                    anchors.verticalCenter: parent.verticalCenter
                    color: ide.rodando ? ide.cLaranja : "#55708a"
                    SequentialAnimation on opacity {
                        running: ide.rodando
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.2; duration: 450 }
                        NumberAnimation { to: 1.0; duration: 450 }
                        onStopped: pulso.opacity = 1
                    }
                }
                Text { text: ide.rodando ? "Claude trabalhando…" : "parado"; color: ide.rodando ? ide.cLaranja : ide.cSuave; font.pixelSize: 12 }
            }
            Item { Layout.fillWidth: true }
            Text { text: "modelo"; color: ide.cSuave; font.pixelSize: 11 }
            ComboBox {
                id: cbModelo
                Layout.preferredWidth: 110
                model: ["sonnet", "opus", "haiku"]
                enabled: !ide.rodando
                onActivated: idx => ide.cmd("modelo", { modelo: ["sonnet", "opus", "haiku"][idx] })
            }
            Text { text: "US$ " + ide.custoTotal.toFixed(3); color: "#ffd27f"; font.pixelSize: 12; font.family: "monospace" }
            BotaoIde { rotulo: "■ Parar"; ativo: ide.rodando; corBorda: "#88ff7f9f"; onClicado: ide.cmd("parar") }
            BotaoIde { rotulo: "＋ Nova sessão"; ativo: !ide.rodando; onClicado: ide.cmd("nova_sessao") }
            BotaoIde { rotulo: "✕ Fechar"; onClicado: ide.fechar() }
        }

        Text {
            Layout.fillWidth: true
            text: (ide.estado ? String(ide.estado.projeto || "") : "sem projeto")
                  + (ide.estado && ide.estado.sessao ? "  ·  sessão " + String(ide.estado.sessao).slice(0, 8) : "  ·  sessão nova")
                  + (ide.online ? "" : "  ·  daemon offline")
            color: "#6f8597"; font.pixelSize: 11; font.family: "monospace"
            elide: Text.ElideMiddle
            textFormat: Text.PlainText
        }

        // ================= CORPO =================
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 8

            // ---------- ÁRVORE ----------
            Rectangle {
                Layout.fillHeight: true
                Layout.preferredWidth: parent.width * 0.20
                color: "#66020810"; radius: 6; border.color: "#337fe6ff"
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 6; spacing: 4
                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "ARQUIVOS"; color: ide.cCiano; font.pixelSize: 11; font.bold: true; font.letterSpacing: 2 }
                        Item { Layout.fillWidth: true }
                        BotaoIde { rotulo: "↑"; ativo: !!(ide.arvore && ide.arvore.rel)
                                   onClicado: ide.cmd("arvore", { rel: ide.pai(ide.arvore.rel) }) }
                        BotaoIde { rotulo: "⟳"; onClicado: ide.cmd("arvore", { rel: (ide.arvore && ide.arvore.rel) ? ide.arvore.rel : "" }) }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: "/" + ((ide.arvore && ide.arvore.rel) ? ide.arvore.rel : "")
                        color: ide.cSuave; font.pixelSize: 11; font.family: "monospace"; elide: Text.ElideLeft
                        textFormat: Text.PlainText
                    }
                    ListView {
                        id: listaArv
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: (ide.arvore && ide.arvore.itens) ? ide.arvore.itens : []
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: Rectangle {
                            id: noArv
                            required property var modelData
                            readonly property bool ehDir: !!modelData.dir
                            readonly property bool aberto: !ehDir && modelData.rel === ide.relAba()
                            width: listaArv.width
                            height: 22
                            color: aberto ? "#2a7fe6ff" : (maArv.containsMouse ? "#147fe6ff" : "transparent")
                            radius: 3
                            Text {
                                x: 4 + (noArv.modelData.nivel || 0) * 12
                                width: parent.width - x - 4
                                anchors.verticalCenter: parent.verticalCenter
                                text: (noArv.ehDir ? "▸ 📁 " : "   📄 ") + noArv.modelData.nome
                                textFormat: Text.PlainText
                                color: noArv.modelData.alterado ? ide.cLaranja : (noArv.ehDir ? ide.cCiano : ide.cTexto)
                                font.pixelSize: 12
                                font.bold: !!noArv.modelData.alterado
                                elide: Text.ElideRight
                            }
                            MouseArea {
                                id: maArv; anchors.fill: parent; hoverEnabled: true
                                onClicked: noArv.ehDir ? ide.cmd("arvore", { rel: noArv.modelData.rel }) : ide.abrirArquivo(noArv.modelData.rel)
                            }
                        }
                        Text {
                            anchors.centerIn: parent
                            visible: listaArv.count === 0
                            text: ide.online ? "(vazio)" : "daemon offline"
                            color: "#6f8597"; font.pixelSize: 12
                        }
                    }
                }
            }

            // ---------- CENTRO + DIREITA + TERMINAL ----------
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 6

                RowLayout {
                    id: meio
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 8

                    // ---------- CÓDIGO ----------
                    Rectangle {
                        Layout.fillHeight: true
                        Layout.preferredWidth: meio.width * 0.56
                        color: "#66020810"; radius: 6; border.color: "#337fe6ff"
                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 6; spacing: 4

                            // abas
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Flickable {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 26
                                    contentWidth: rowAbas.implicitWidth
                                    clip: true
                                    flickableDirection: Flickable.HorizontalFlick
                                    Row {
                                        id: rowAbas
                                        spacing: 3
                                        Repeater {
                                            model: abas
                                            Rectangle {
                                                id: aba
                                                required property int index
                                                required property string rel
                                                readonly property bool sel: index === ide.abaAtual
                                                width: abaTxt.implicitWidth + 34; height: 26; radius: 4
                                                color: sel ? "#337fe6ff" : (abaMa.containsMouse ? "#147fe6ff" : "transparent")
                                                border.color: sel ? ide.cCiano : "#337fe6ff"
                                                MouseArea { id: abaMa; anchors.fill: parent; hoverEnabled: true
                                                            onClicked: { ide.abaAtual = aba.index; ide.mostrarDiff = false } }
                                                Text {
                                                    id: abaTxt
                                                    x: 8; anchors.verticalCenter: parent.verticalCenter
                                                    text: ide.nomeBase(aba.rel)
                                                    textFormat: Text.PlainText
                                                    color: ide.diffDe(aba.rel) !== "" ? ide.cLaranja : ide.cTexto
                                                    font.pixelSize: 11
                                                }
                                                Text {
                                                    anchors.right: parent.right; anchors.rightMargin: 6
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    text: "✕"; color: xMa.containsMouse ? ide.cVermelho : ide.cSuave; font.pixelSize: 10
                                                    MouseArea {
                                                        id: xMa; anchors.fill: parent; anchors.margins: -4; hoverEnabled: true
                                                        onClicked: {
                                                            const i = aba.index
                                                            abas.remove(i)
                                                            if (ide.abaAtual >= abas.count) ide.abaAtual = abas.count - 1
                                                            else if (i < ide.abaAtual) ide.abaAtual--
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                                BotaoIde {
                                    readonly property bool temDiff: ide.diffDe(ide.relAba()) !== ""
                                    visible: temDiff || ide.mostrarDiff
                                    rotulo: ide.mostrarDiff ? "ver código" : "ver diff"
                                    corBorda: "#88ff8a1f"
                                    onClicado: ide.mostrarDiff = !ide.mostrarDiff
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                visible: ide.abaAtual >= 0
                                readonly property var a: (ide.abaAtual >= 0 && ide.abaAtual < abas.count) ? abas.get(ide.abaAtual) : null
                                text: a ? (a.rel + "  ·  " + a.linhas + " linhas" + (a.truncado ? "  ·  TRUNCADO (300 KB)" : "")) : ""
                                textFormat: Text.PlainText
                                color: "#6f8597"; font.pixelSize: 11; font.family: "monospace"; elide: Text.ElideMiddle
                            }

                            Item {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true

                                Text {
                                    anchors.centerIn: parent
                                    visible: ide.abaAtual < 0
                                    text: "Abra um arquivo na árvore\nou peça algo ao Claude →"
                                    horizontalAlignment: Text.AlignHCenter
                                    color: "#6f8597"; font.pixelSize: 13
                                }

                                // código
                                Flickable {
                                    id: flCodigo
                                    anchors.fill: parent
                                    visible: ide.abaAtual >= 0 && !ide.mostrarDiff
                                    clip: true
                                    contentWidth: Math.max(width, rowCod.implicitWidth)
                                    contentHeight: rowCod.implicitHeight
                                    boundsBehavior: Flickable.StopAtBounds
                                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                    ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                                    readonly property string codigo: (ide.abaAtual >= 0 && ide.abaAtual < abas.count) ? abas.get(ide.abaAtual).texto : ""
                                    readonly property int nLinhas: codigo === "" ? 0 : codigo.split("\n").length
                                    onCodigoChanged: { contentY = 0; contentX = 0 }
                                    Row {
                                        id: rowCod
                                        spacing: 10
                                        Rectangle {
                                            width: nums.implicitWidth + 10
                                            height: Math.max(nums.implicitHeight, codigo.implicitHeight)
                                            color: "#33000000"
                                            Text {
                                                id: nums
                                                anchors.right: parent.right; anchors.rightMargin: 5
                                                text: ide.numeros(flCodigo.nLinhas)
                                                textFormat: Text.PlainText
                                                horizontalAlignment: Text.AlignRight
                                                color: "#55708a"
                                                font.family: "monospace"; font.pixelSize: 12
                                            }
                                        }
                                        TextEdit {
                                            id: codigo
                                            text: flCodigo.codigo
                                            textFormat: TextEdit.PlainText
                                            readOnly: true
                                            selectByMouse: true
                                            persistentSelection: true
                                            color: ide.cTexto
                                            selectionColor: "#557fe6ff"
                                            selectedTextColor: "#ffffff"
                                            font.family: "monospace"; font.pixelSize: 12
                                        }
                                    }
                                }

                                // diff
                                Flickable {
                                    anchors.fill: parent
                                    visible: ide.abaAtual >= 0 && ide.mostrarDiff
                                    clip: true
                                    contentWidth: width
                                    contentHeight: dvCentro.implicitHeight
                                    boundsBehavior: Flickable.StopAtBounds
                                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                    DiffLinhas {
                                        id: dvCentro
                                        width: parent.width - 10
                                        diff: ide.mostrarDiff ? ide.diffDe(ide.relAba()) : ""
                                    }
                                }
                            }
                        }
                    }

                    // ---------- CONVERSA ----------
                    Rectangle {
                        Layout.fillHeight: true
                        Layout.fillWidth: true
                        color: "#66020810"; radius: 6; border.color: "#337fe6ff"
                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 6; spacing: 6
                            Text { text: "CONVERSA COM O CLAUDE"; color: ide.cCiano; font.pixelSize: 11; font.bold: true; font.letterSpacing: 2 }

                            ListView {
                                id: chat
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                spacing: 6
                                model: ide.eventos
                                property bool noFim: true
                                onContentYChanged: noFim = atYEnd
                                onCountChanged: if (noFim) Qt.callLater(positionViewAtEnd)
                                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                                Text {
                                    anchors.centerIn: parent
                                    width: parent.width - 20
                                    visible: chat.count === 0
                                    horizontalAlignment: Text.AlignHCenter
                                    wrapMode: Text.Wrap
                                    text: "Nada ainda. Escreva abaixo o que o Claude deve programar neste projeto."
                                    color: "#6f8597"; font.pixelSize: 12
                                }

                                delegate: Item {
                                    id: ev
                                    required property var model
                                    readonly property string kind: String(model.kind || "")
                                    readonly property string texto: String(model.texto || "")
                                    readonly property bool ehErro: String(model.erro) === "true" || String(model.erro) === "True" || String(model.erro) === "1"
                                    property bool aberto: false
                                    width: chat.width - 8
                                    height: colEv.implicitHeight

                                    Column {
                                        id: colEv
                                        width: parent.width
                                        spacing: 2

                                        // usuário (balão à direita)
                                        Item {
                                            visible: ev.kind === "usuario"
                                            width: parent.width
                                            height: visible ? balao.height : 0
                                            Rectangle {
                                                id: balao
                                                anchors.right: parent.right
                                                width: Math.min(parent.width * 0.85, txtU.implicitWidth + 20)
                                                height: txtU.implicitHeight + 14
                                                radius: 10
                                                color: "#33ff8a1f"; border.color: "#88ff8a1f"
                                                Text {
                                                    id: txtU
                                                    x: 10; y: 7
                                                    width: Math.min(implicitWidth, ev.width * 0.85 - 20)
                                                    text: ev.texto
                                                    textFormat: Text.PlainText
                                                    wrapMode: Text.Wrap
                                                    color: "#ffe6cc"; font.pixelSize: 13
                                                }
                                            }
                                        }

                                        // resposta do Claude
                                        TextEdit {
                                            visible: ev.kind === "texto"
                                            width: parent.width
                                            height: visible ? implicitHeight : 0
                                            text: ev.texto
                                            textFormat: TextEdit.PlainText
                                            readOnly: true; selectByMouse: true
                                            wrapMode: TextEdit.Wrap
                                            color: ide.cTexto; font.pixelSize: 13
                                            selectionColor: "#557fe6ff"
                                        }

                                        // pensamento (recolhido)
                                        Text {
                                            visible: ev.kind === "pensamento"
                                            width: parent.width
                                            height: visible ? implicitHeight : 0
                                            text: (ev.aberto ? "▾ " : "▸ ") + "pensando… " + ev.texto
                                            textFormat: Text.PlainText
                                            wrapMode: Text.Wrap
                                            maximumLineCount: ev.aberto ? 500 : 1
                                            elide: Text.ElideRight
                                            font.italic: true; font.pixelSize: 12
                                            color: "#b9a6d9"
                                            MouseArea { anchors.fill: parent; onClicked: ev.aberto = !ev.aberto }
                                        }

                                        // ferramenta / resultado / terminal (linha compacta)
                                        Rectangle {
                                            visible: ev.kind === "ferramenta" || ev.kind === "resultado" || ev.kind === "terminal"
                                            width: parent.width
                                            height: visible ? colF.implicitHeight + 6 : 0
                                            radius: 4
                                            color: ev.ehErro ? "#26ff7f9f" : (fMa.containsMouse ? "#147fe6ff" : "#0d7fe6ff")
                                            Column {
                                                id: colF
                                                x: 6; y: 3; width: parent.width - 12; spacing: 2
                                                Text {
                                                    width: parent.width
                                                    textFormat: Text.PlainText
                                                    elide: Text.ElideRight
                                                    font.family: "monospace"; font.pixelSize: 11
                                                    color: ev.ehErro ? ide.cVermelho : (ev.kind === "resultado" ? ide.cSuave : ide.cRoxo)
                                                    text: ev.kind === "terminal" ? ("$ " + String(ev.model.comando || ""))
                                                        : ev.kind === "resultado" ? ("  ↳ " + (ev.ehErro ? "erro: " : "") + ev.texto.split("\n")[0])
                                                        : ("⚙ " + String(ev.model.nome || "") + "  " + String(ev.model.resumo || ""))
                                                }
                                                Text {
                                                    visible: ev.aberto
                                                    width: parent.width
                                                    textFormat: Text.PlainText
                                                    wrapMode: Text.WrapAnywhere
                                                    maximumLineCount: 60
                                                    elide: Text.ElideRight
                                                    font.family: "monospace"; font.pixelSize: 11
                                                    color: "#cfe9d6"
                                                    text: ev.kind === "terminal" ? String(ev.model.saida || "")
                                                        : ev.kind === "resultado" ? ev.texto
                                                        : String(ev.model.args || "")
                                                }
                                            }
                                            MouseArea { id: fMa; anchors.fill: parent; hoverEnabled: true; onClicked: ev.aberto = !ev.aberto }
                                        }

                                        // edição (cartão com diff)
                                        Rectangle {
                                            visible: ev.kind === "edicao"
                                            width: parent.width
                                            height: visible ? colE.implicitHeight + 10 : 0
                                            radius: 6
                                            color: "#1a7fffb0"; border.color: "#557fffb0"
                                            Column {
                                                id: colE
                                                x: 6; y: 5; width: parent.width - 12; spacing: 4
                                                RowLayout {
                                                    width: parent.width
                                                    Text {
                                                        Layout.fillWidth: true
                                                        text: "✎ " + String(ev.model.arquivo || "")
                                                        textFormat: Text.PlainText
                                                        elide: Text.ElideMiddle
                                                        color: ide.cVerde; font.pixelSize: 12; font.bold: true; font.family: "monospace"
                                                    }
                                                    BotaoIde { rotulo: ev.aberto ? "recolher" : "diff"; onClicado: ev.aberto = !ev.aberto }
                                                    BotaoIde {
                                                        rotulo: "abrir"
                                                        onClicado: { ide.abrirArquivo(String(ev.model.arquivo || "")); ide.mostrarDiff = true }
                                                    }
                                                }
                                                DiffLinhas {
                                                    width: parent.width
                                                    maxLinhas: ev.aberto ? 400 : 8
                                                    diff: ev.kind === "edicao" ? String(ev.model.diff || "") : ""
                                                }
                                            }
                                        }

                                        // fim
                                        Text {
                                            visible: ev.kind === "fim"
                                            width: parent.width
                                            height: visible ? implicitHeight : 0
                                            text: "✓ concluído · " + Number(ev.model.dur_s || 0).toFixed(1) + " s · "
                                                  + String(ev.model.turnos || "?") + " turnos · US$ " + Number(ev.model.custo || 0).toFixed(4)
                                            textFormat: Text.PlainText
                                            color: "#ffd27f"; font.pixelSize: 11; font.family: "monospace"
                                        }

                                        // início
                                        Text {
                                            visible: ev.kind === "inicio"
                                            width: parent.width
                                            height: visible ? implicitHeight : 0
                                            text: "▶ " + String(ev.model.modelo || "") + (ev.model.sessao ? " · sessão " + String(ev.model.sessao).slice(0, 8) : "")
                                            textFormat: Text.PlainText
                                            color: "#6f8597"; font.pixelSize: 10; font.family: "monospace"
                                        }

                                        // erro
                                        Rectangle {
                                            visible: ev.kind === "erro"
                                            width: parent.width
                                            height: visible ? txtErr.implicitHeight + 10 : 0
                                            radius: 4
                                            color: "#33ff7f9f"; border.color: "#88ff7f9f"
                                            Text {
                                                id: txtErr
                                                x: 6; y: 5; width: parent.width - 12
                                                text: "⚠ " + ev.texto
                                                textFormat: Text.PlainText
                                                wrapMode: Text.WrapAnywhere
                                                color: ide.cVermelho; font.pixelSize: 12
                                            }
                                        }
                                    }
                                }
                            }

                            // entrada
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: Math.min(140, Math.max(44, entrada.implicitHeight + 8))
                                    radius: 6
                                    color: "#88020810"
                                    border.color: entrada.activeFocus ? ide.cCiano : "#447fe6ff"
                                    ScrollView {
                                        anchors.fill: parent
                                        anchors.margins: 2
                                        TextArea {
                                            id: entrada
                                            placeholderText: "Peça ao Claude: ex. crie um endpoint..."
                                            placeholderTextColor: "#6f8597"
                                            color: ide.cTexto
                                            font.pixelSize: 13
                                            wrapMode: TextArea.Wrap
                                            textFormat: TextEdit.PlainText
                                            selectByMouse: true
                                            background: null
                                            Keys.onPressed: e => {
                                                if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && !(e.modifiers & Qt.ShiftModifier)) {
                                                    e.accepted = true
                                                    ide.enviar()
                                                }
                                            }
                                        }
                                    }
                                }
                                BotaoIde {
                                    Layout.preferredHeight: 44
                                    rotulo: ide.rodando ? "…" : "Enviar ➤"
                                    ativo: !ide.rodando && ide.online && entrada.text.trim() !== ""
                                    corBorda: "#88ff8a1f"
                                    onClicado: ide.enviar()
                                }
                            }
                        }
                    }
                }

                // ---------- TERMINAL ----------
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: ide.termAberto ? meio.height * 0.28 + 30 : 28
                    color: "#99000000"; radius: 6; border.color: "#337fe6ff"
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 6; spacing: 4
                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: (ide.termAberto ? "▾ " : "▸ ") + "TERMINAL"
                                color: ide.cCiano; font.pixelSize: 11; font.bold: true; font.letterSpacing: 2
                                MouseArea { anchors.fill: parent; onClicked: ide.termAberto = !ide.termAberto }
                            }
                            Item { Layout.fillWidth: true }
                        }
                        ListView {
                            id: term
                            visible: ide.termAberto
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            model: ide.eventos
                            property bool noFim: true
                            onContentYChanged: noFim = atYEnd
                            onCountChanged: if (noFim) Qt.callLater(positionViewAtEnd)
                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                            delegate: Column {
                                id: tl
                                required property var model
                                readonly property bool mostra: String(model.kind || "") === "terminal"
                                readonly property bool ehErro: String(model.erro) === "true" || String(model.erro) === "True" || String(model.erro) === "1"
                                width: term.width - 10
                                visible: mostra
                                height: mostra ? implicitHeight : 0
                                spacing: 1
                                Text {
                                    width: parent.width
                                    text: "$ " + String(tl.model.comando || "")
                                    textFormat: Text.PlainText
                                    wrapMode: Text.WrapAnywhere
                                    color: ide.cVerde; font.family: "monospace"; font.pixelSize: 12
                                }
                                TextEdit {
                                    width: parent.width
                                    visible: text !== ""
                                    text: tl.mostra ? String(tl.model.saida || "") : ""
                                    textFormat: TextEdit.PlainText
                                    readOnly: true; selectByMouse: true
                                    wrapMode: TextEdit.WrapAnywhere
                                    color: tl.ehErro ? ide.cVermelho : "#c8d6e2"
                                    font.family: "monospace"; font.pixelSize: 12
                                    selectionColor: "#557fe6ff"
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
