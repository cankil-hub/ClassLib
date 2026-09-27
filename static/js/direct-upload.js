(() => {
    const form = document.getElementById('direct-upload');
    if (!form) return;
    const input = document.getElementById('upload-file');
    const status = document.getElementById('upload-status');
    const progress = document.getElementById('upload-progress');
    const button = form.querySelector('button');
    const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;
    let pendingComplete = null;

    async function post(url, data = {}) {
        const response = await fetch(url, {
            method: 'POST', credentials: 'same-origin',
            headers: {'X-CSRFToken': csrf}, body: new URLSearchParams(data),
        });
        if (response.redirected) throw new Error('登录已过期，请重新登录后上传。');
        let result;
        try { result = await response.json(); }
        catch { throw new Error('请求失败，请稍后重试。'); }
        if (!response.ok) throw new Error(result.error || '请求失败，请稍后重试。');
        return result;
    }

    function put(url, file, contentType) {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('PUT', url);
            xhr.setRequestHeader('Content-Type', contentType);
            xhr.timeout = 10 * 60 * 1000;
            xhr.upload.onprogress = (event) => {
                if (event.lengthComputable) progress.value = event.loaded / event.total * 100;
            };
            xhr.onload = () => xhr.status >= 200 && xhr.status < 300
                ? resolve() : reject(new Error('文件传输失败，请重新上传。'));
            xhr.onerror = () => reject(new Error('网络连接失败，请重新上传。'));
            xhr.ontimeout = () => reject(new Error('上传超时，请重新上传。'));
            // Browser sets Content-Length, which is included in the signature.
            xhr.send(file);
        });
    }

    input.addEventListener('change', () => {
        pendingComplete = null;
        button.textContent = '上传';
        status.textContent = '';
        progress.value = 0;
    });
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const file = input.files[0];
        if (!file) return;
        if (!file.size || file.size > Number(form.dataset.maxSize)) {
            status.textContent = '请选择非空且不超过 50 MiB 的文件。';
            return;
        }
        button.disabled = true;
        input.disabled = true;
        try {
            if (!pendingComplete) {
                status.textContent = '正在准备上传…';
                const ticket = await post(form.dataset.beginUrl, {name: file.name, size: file.size});
                progress.hidden = false;
                progress.value = 0;
                status.textContent = '正在上传，请勿关闭页面…';
                await put(ticket.upload_url, file, ticket.content_type);
                pendingComplete = ticket.complete_url;
            }
            status.textContent = '上传完成，正在校验文件…';
            const result = await post(pendingComplete);
            window.location.assign(result.redirect_url);
        } catch (error) {
            status.textContent = error.message;
            button.textContent = pendingComplete ? '重试确认上传' : '重新上传';
        } finally {
            button.disabled = false;
            input.disabled = false;
        }
    });
})();
