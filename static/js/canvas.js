// ======================================
// SketchRoute Canvas
// ======================================

let canvas = null;

let currentTool = 'select';

// ======================================
// Inicialización
// ======================================

function initCanvas(savedData = null) {

    canvas = new fabric.Canvas(
        'editorCanvas',
        {
            width: 1400,
            height: 900,
            backgroundColor: '#ffffff',
            selection: true
        }
    );

    if (savedData) {

        canvas.loadFromJSON(
            savedData,
            () => {
                canvas.renderAll();
            }
        );
    }

    setupEvents();
}

// ======================================
// Eventos
// ======================================

function setupEvents() {

    canvas.on(
        'mouse:down',
        function (event) {

            const pointer =
                canvas.getPointer(event.e);

            if (currentTool === 'wall') {

                createWall(
                    pointer.x,
                    pointer.y
                );
            }

            if (currentTool === 'door') {

                createDoor(
                    pointer.x,
                    pointer.y
                );
            }

            if (currentTool === 'exit') {

                createExit(
                    pointer.x,
                    pointer.y
                );
            }

        }
    );
}

// ======================================
// Herramientas
// ======================================

function setTool(tool, button) {

    currentTool = tool;

    document
        .querySelectorAll('.tool-btn')
        .forEach(btn => {

            btn.classList.remove(
                'active'
            );

        });

    button.classList.add(
        'active'
    );
}

// ======================================
// Objetos
// ======================================

function createWall(x, y) {

    const wall = new fabric.Line(
        [
            x,
            y,
            x + 120,
            y
        ],
        {
            stroke: '#222',
            strokeWidth: 5
        }
    );

    canvas.add(wall);
}

function createDoor(x, y) {

    const door = new fabric.Rect({
        left: x,
        top: y,
        width: 40,
        height: 10,
        fill: '#4caf50'
    });

    canvas.add(door);
}

function createExit(x, y) {

    const exit = new fabric.Triangle({
        left: x,
        top: y,
        width: 25,
        height: 25,
        fill: '#f44336'
    });

    canvas.add(exit);
}

// ======================================
// Cargar imagen
// ======================================

document.addEventListener(
    'DOMContentLoaded',
    function () {

        initCanvas(
            typeof SAVED_DATA !== 'undefined'
                ? SAVED_DATA
                : null
        );

        const uploadBtn =
            document.getElementById(
                'uploadBtn'
            );

        uploadBtn.addEventListener(
            'click',
            function () {

                const input =
                    document.createElement(
                        'input'
                    );

                input.type = 'file';

                input.accept =
                    'image/*';

                input.click();

                input.onchange =
                    function (e) {

                        const file =
                            e.target.files[0];

                        const url =
                            URL.createObjectURL(
                                file
                            );

                        fabric.Image.fromURL(
                            url,
                            function (img) {

                                img.selectable =
                                    false;

                                canvas.setBackgroundImage(
                                    img,
                                    canvas.renderAll.bind(
                                        canvas
                                    ),
                                    {
                                        scaleX:
                                            canvas.width /
                                            img.width,

                                        scaleY:
                                            canvas.height /
                                            img.height
                                    }
                                );
                            }
                        );
                    };
            }
        );

        const saveBtn =
            document.getElementById(
                'saveBtn'
            );

        saveBtn.addEventListener(
            'click',
            function () {

                const data =
                    canvas.toJSON();

                console.log(
                    JSON.stringify(
                        data,
                        null,
                        2
                    )
                );

                alert(
                    'Plano guardado en consola'
                );
            }
        );
    }
);