const URL_CANDIDATE = /https?:\/\/[^\s\])>]+/gi;

function cleanCandidate(value) {
  return value
    .replace(/\\([&_])/g, '$1')
    .replace(/[.,;]+$/, '');
}

export function parseIptvList(input) {
  const candidates = input.match(URL_CANDIDATE) ?? [];
  const unique = new Map();
  let rejected = 0;

  for (const raw of candidates) {
    try {
      const parsed = new URL(cleanCandidate(raw));
      const username = parsed.searchParams.get('username');
      const password = parsed.searchParams.get('password');
      if (!username || !password || !/^https?:$/.test(parsed.protocol)) {
        rejected += 1;
        continue;
      }
      const server = `${parsed.protocol}//${parsed.host}`;
      const key = `${server}\0${username}\0${password}`;
      unique.set(key, { server, username, password, source: parsed.href });
    } catch {
      rejected += 1;
    }
  }

  return { entries: [...unique.values()], rejected, candidates: candidates.length };
}

export function toCsv(entries) {
  const quote = (value) => `"${String(value).replaceAll('"', '""')}"`;
  return ['servidor,usuario,contraseña', ...entries.map((item) =>
    [item.server, item.username, item.password].map(quote).join(','))].join('\n');
}
