import express from 'express';
import http from 'http';
import { spawn, ChildProcess } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = 3000;
const FASTAPI_PORT = 8005;

let pythonProcess: ChildProcess | null = null;

function startFastAPI() {
  console.log('[PayFlow] Starting FastAPI Uvicorn backend on port 8000...');
  pythonProcess = spawn('python3', ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', String(FASTAPI_PORT)], {
    stdio: 'inherit',
    cwd: __dirname,
  });

  pythonProcess.on('exit', (code, signal) => {
    console.log(`[PayFlow] FastAPI process exited with code ${code} (${signal})`);
  });
}

function proxyToFastAPI(req: express.Request, res: express.Response) {
  const options: http.RequestOptions = {
    hostname: '127.0.0.1',
    port: FASTAPI_PORT,
    path: req.originalUrl,
    method: req.method,
    headers: {
      ...req.headers,
      host: `127.0.0.1:${FASTAPI_PORT}`,
    },
  };

  const proxyReq = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode || 500, proxyRes.headers);
    proxyRes.pipe(res, { end: true });
  });

  proxyReq.on('error', (err) => {
    console.error('[PayFlow Proxy Error]', err.message);
    if (!res.headersSent) {
      res.status(503).json({
        error: 'FastAPI Backend Starting Up',
        message: 'The PayFlow Python backend is initializing. Please retry in 2 seconds.',
      });
    }
  });

  req.pipe(proxyReq, { end: true });
}

async function createServer() {
  startFastAPI();

  const app = express();

  // Proxy API and Swagger documentation to FastAPI
  app.use('/api', proxyToFastAPI);
  app.use('/docs', proxyToFastAPI);
  app.use('/redoc', proxyToFastAPI);
  app.use('/openapi.json', proxyToFastAPI);

  // Serve built SPA in production, or mount Vite development middleware in dev
  const isProd = process.env.NODE_ENV === 'production';
  if (isProd) {
    const distPath = path.join(__dirname, 'dist');
    app.use(express.static(distPath));
    app.get('*', (req, res, next) => {
      if (req.path.startsWith('/api') || req.path.startsWith('/docs') || req.path.startsWith('/redoc') || req.path.startsWith('/openapi.json')) {
        return next();
      }
      res.sendFile(path.join(distPath, 'index.html'));
    });
  } else {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  }

  const server = app.listen(PORT, '0.0.0.0', () => {
    console.log(`[PayFlow] System running on http://0.0.0.0:${PORT}`);
    console.log(`[PayFlow] Swagger API Docs available at http://0.0.0.0:${PORT}/docs`);
  });

  const cleanup = () => {
    if (pythonProcess) {
      console.log('[PayFlow] Terminating Python backend...');
      pythonProcess.kill();
    }
    server.close();
    process.exit(0);
  };

  process.on('SIGINT', cleanup);
  process.on('SIGTERM', cleanup);
}

createServer().catch((err) => {
  console.error('Failed to start PayFlow server:', err);
  process.exit(1);
});
