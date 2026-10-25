export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // 1. Redirect root bare domain (surepups.com) to www.surepups.com
    if (url.hostname === 'surepups.com') {
      url.hostname = 'www.surepups.com';
      return Response.redirect(url.toString(), 301);
    }

    // 2. Redirect root path ('/' or '') to /home.html
    if (url.hostname === 'www.surepups.com' && (url.pathname === '/' || url.pathname === '')) {
      url.pathname = '/home.html';
      return Response.redirect(url.toString(), 302);
    }

    // 3. Otherwise, serve static assets normally from Cloudflare's asset binding
    return env.ASSETS.fetch(request);
  }
};
