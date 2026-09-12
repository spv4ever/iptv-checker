import test from 'node:test';
import assert from 'node:assert/strict';
import { parseIptvList, toCsv } from '../parser.js';

test('descarta texto y separa las credenciales de una URL', () => {
  const result = parseIptvList('USAR VPN\nhttp://demo.test:8080/get.php?username=ana&password=secreta&type=m3u_plus');
  assert.deepEqual(result.entries[0], {
    server: 'http://demo.test:8080', username: 'ana', password: 'secreta',
    source: 'http://demo.test:8080/get.php?username=ana&password=secreta&type=m3u_plus'
  });
});

test('acepta enlaces Markdown escapados y elimina duplicados', () => {
  const url = 'https://demo.test/get.php?username=u\\&password=p\\&type=m3u_plus';
  const result = parseIptvList(`[texto](${url})\n${url}`);
  assert.equal(result.entries.length, 1);
});

test('rechaza URLs que no contienen ambos campos', () => {
  const result = parseIptvList('https://demo.test/get.php?username=ana');
  assert.equal(result.entries.length, 0);
  assert.equal(result.rejected, 1);
});

test('genera un CSV con encabezados y valores escapados', () => {
  assert.equal(toCsv([{ server: 'https://x.test', username: 'a,b', password: 'p"q' }]),
    'servidor,usuario,contraseña\n"https://x.test","a,b","p""q"');
});
