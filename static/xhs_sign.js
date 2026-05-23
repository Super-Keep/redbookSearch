/**
 * XHS Sign Bridge Script
 *
 * Generates x-s, x-t, x-s-common sign parameters by calling
 * the Spider_XHS sign algorithm (xhs_main_260411.js).
 *
 * Input (JSON via stdin):
 *   { "path": "/api/sns/web/v1/search/notes", "payload": "{...}", "cookie": "a1=xxx;..." }
 *
 * Output (JSON to stdout):
 *   { "x-s": "...", "x-t": "...", "x-s-common": "..." }
 */

const { get_request_headers_params } = require('./xhs_main_260411.js');

let inputData = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
    inputData += chunk;
});

process.stdin.on('end', () => {
    try {
        const input = JSON.parse(inputData);
        const { path, payload, cookie } = input;

        // Extract a1 from cookie string
        const a1Match = cookie.match(/a1=([^;]+)/);
        const a1 = a1Match ? a1Match[1] : '';

        if (!a1) {
            process.stderr.write('Error: a1 not found in cookie\n');
            process.exit(1);
        }

        // Call the real sign algorithm
        const result = get_request_headers_params(path, payload, a1, 'POST');

        const output = {
            'x-s': result.xs || '',
            'x-t': String(result.xt || Date.now()),
            'x-s-common': result.xs_common || '',
        };

        process.stdout.write(JSON.stringify(output));
        process.exit(0);

    } catch (err) {
        process.stderr.write(`Sign error: ${err.message}\n${err.stack}\n`);
        process.exit(1);
    }
});
