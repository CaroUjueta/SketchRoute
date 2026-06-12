// SketchRoute — canvas.js
// Editor de planos con Fabric.js

let canvas = null;
let currentTool = 'select';

function initCanvas(savedData) {
    canvas = new fabric.Canvas('floorCanvas', {
        isDrawingMode: false,
        selection: true,
        backgroundColor: '#ffffff',
    });

    if (savedData) {
        canvas.loadFromJSON(savedData, canvas.renderAll.bind(canvas));
    }

    canvas.on('mouse:down', function(options) {
        if (currentTool === 'wall') {
            const pointer = canvas.getPointer(options.e);
            const line = new fabric.Line([pointer.x, pointer.y, pointer.x + 100, pointer.y], {
                stroke: '#333',
                strokeWidth: 4,
                selectable: true,
                evented: true,
            });
            canvas.add(line);
            canvas.renderAll();
        }
    });
}

function setTool(tool) {
    currentTool = tool;
    document.querySelectorAll('.tool-btn').forEach(btn => btn.classList.remove('active'));
    event.target.classList.add('active');
    if (canvas) {
        canvas.isDrawingMode = false;
    }
}

function calculateRoutes() {
    if (!canvas) return;
    const data = JSON.stringify(canvas.toJSON());
    fetch(`/routing/calculate/${PLAN_ID}/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken'),
        },
        body: JSON.stringify({ canvas_data: data }),
    }).then(r => r.json()).then(data => {
        alert(data.message || 'Rutas calculadas');
    });
}

function autoPlaceSignals() {
    fetch(`/signaling/auto-place/${PLAN_ID}/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': getCookie('csrftoken') },
    }).then(r => r.json()).then(data => {
        alert(data.message || 'Señales colocadas');
    });
}

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}
