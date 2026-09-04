// Reusable attachment picker: lets the person add files across multiple
// browse clicks (native <input type=file> otherwise replaces the
// selection each time) and supports drag-and-drop. Each picker keeps its
// own in-memory file list and rebuilds the underlying <input>'s FileList
// via DataTransfer before submit, so the form still posts normally.
function initAttachmentPicker(containerId) {
    var container = document.getElementById(containerId);
    if (!container) return;

    var dropZone = container.querySelector('.attachment-dropzone');
    var input = container.querySelector('input[type=file]');
    var list = container.querySelector('.attachment-filelist');
    var files = [];

    function formatSize(bytes) {
        if (bytes >= 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
        return Math.ceil(bytes / 1024) + ' KB';
    }

    function render() {
        list.innerHTML = '';
        files.forEach(function (file, idx) {
            var li = document.createElement('li');
            li.className = 'attachment-staged';

            var name = document.createElement('span');
            name.className = 'staged-name';
            name.textContent = file.name;

            var size = document.createElement('span');
            size.className = 'staged-size';
            size.textContent = formatSize(file.size);

            var remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'staged-remove';
            remove.setAttribute('aria-label', 'Remove ' + file.name);
            remove.textContent = '\u00d7';
            remove.addEventListener('click', function () {
                files.splice(idx, 1);
                sync();
            });

            li.appendChild(name);
            li.appendChild(size);
            li.appendChild(remove);
            list.appendChild(li);
        });
    }

    function sync() {
        var dt = new DataTransfer();
        files.forEach(function (f) { dt.items.add(f); });
        input.files = dt.files;
        render();
    }

    function addFiles(fileList) {
        Array.prototype.forEach.call(fileList, function (f) {
            var alreadyStaged = files.some(function (existing) {
                return existing.name === f.name && existing.size === f.size;
            });
            if (!alreadyStaged) files.push(f);
        });
        sync();
    }

    dropZone.addEventListener('click', function () { input.click(); });
    dropZone.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            input.click();
        }
    });

    // The change event only carries the newly-picked batch — addFiles()
    // merges it with what's already staged rather than replacing it.
    input.addEventListener('change', function () {
        addFiles(input.files);
    });

    ['dragenter', 'dragover'].forEach(function (evt) {
        dropZone.addEventListener(evt, function (e) {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });
    });
    ['dragleave', 'drop'].forEach(function (evt) {
        dropZone.addEventListener(evt, function (e) {
            e.preventDefault();
            dropZone.classList.remove('dragover');
        });
    });
    dropZone.addEventListener('drop', function (e) {
        if (e.dataTransfer && e.dataTransfer.files) {
            addFiles(e.dataTransfer.files);
        }
    });
}
