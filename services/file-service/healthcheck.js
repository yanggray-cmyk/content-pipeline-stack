const http = require('http');
http.get('http://127.0.0.1:18098/health', (res) => {
    if (res.statusCode === 200) process.exit(0);
    process.exit(1);
}).on('error', () => process.exit(1));
