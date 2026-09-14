import { execFile, spawn, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { app } from 'electron';

import { generateLaunchSecret } from './secret';

/**
 * Spawning and supervising the Python service.
 *
 * The main process owns this because the renderer must not: it holds the port and the secret, and
 * it is the only thing that can restart the service when it dies. See docs/specs/v1-spectrapaint.md.
 */

const HANDSHAKE_PREFIX = 'SPECTRAPAINT_HANDSHAKE ';
const SECRET_ENV_VAR = 'SPECTRAPAINT_SECRET';
const HOST = '127.0.0.1';

const START_TIMEOUT_MS = 20_000;
const READY_POLL_INTERVAL_MS = 150;

/** Restarting forever would hide a service that cannot run on this machine at all. */
const MAX_RESTARTS = 3;
const RESTART_WINDOW_MS = 60_000;

/** Codes the boot screen maps to plain language. Never shown raw to the Dealer. */
export type SidecarFailure =
  'service_missing' | 'service_exited' | 'service_timeout' | 'service_unreachable';

export class SidecarStartError extends Error {
  constructor(
    readonly code: SidecarFailure,
    message: string,
  ) {
    super(message);
    this.name = 'SidecarStartError';
  }
}

export type SidecarPhase = 'starting' | 'ready' | 'restarting' | 'failed';

export interface SidecarOptions {
  onPhase?: (phase: SidecarPhase) => void;
  hardwareProfile?: string;
  qualityTier?: string;
}

export interface Sidecar {
  /** Read through a getter, never captured: a restart changes the port. */
  readonly baseUrl: string;
  readonly secret: string;
  stop(): Promise<void>;
}

interface LaunchCommand {
  command: string;
  args: string[];
  cwd: string;
}

/**
 * Where the service lives, in development and once packaged.
 *
 * Development runs the uv-managed virtualenv directly, so there is no build step between editing
 * the service and running the app. A packaged build runs the frozen PyInstaller binary shipped in
 * resources (docs/design-decisions.md §3).
 */
function resolveLaunchCommand(): LaunchCommand {
  const onWindows = process.platform === 'win32';

  if (app.isPackaged) {
    const binary = onWindows ? 'spectrapaint-service.exe' : 'spectrapaint-service';
    const directory = path.join(process.resourcesPath, 'service');
    return { command: path.join(directory, binary), args: [], cwd: directory };
  }

  // apps/desktop/out -> repository root
  const repositoryRoot = path.join(__dirname, '..', '..', '..');
  const serviceRoot = path.join(repositoryRoot, 'services', 'inference');
  const python = onWindows
    ? path.join(serviceRoot, '.venv', 'Scripts', 'python.exe')
    : path.join(serviceRoot, '.venv', 'bin', 'python');

  return { command: python, args: ['-m', 'spectrapaint'], cwd: serviceRoot };
}

/**
 * Kill the service and everything it started.
 *
 * Windows has no signals: `child.kill()` maps to TerminateProcess and does not touch descendants,
 * so a child spawned under a shell survives and keeps holding its port. `taskkill /T` is what
 * actually cleans up — see docs/design-decisions.md §9c, which exists partly because this failure
 * passes on Linux.
 */
function killProcessTree(child: ChildProcess): Promise<void> {
  return new Promise((resolve) => {
    const pid = child.pid;
    if (pid === undefined || child.exitCode !== null) {
      resolve();
      return;
    }

    if (process.platform === 'win32') {
      execFile('taskkill', ['/pid', String(pid), '/T', '/F'], () => resolve());
      return;
    }

    child.once('exit', () => resolve());
    child.kill('SIGTERM');
    // A service wedged mid-request should not hold up quitting.
    setTimeout(() => {
      if (child.exitCode === null) child.kill('SIGKILL');
      resolve();
    }, 5_000).unref();
  });
}

/** Read stdout line by line, since a chunk is not a line. */
function onEachLine(stream: NodeJS.ReadableStream, handle: (line: string) => void): void {
  let buffered = '';
  stream.setEncoding('utf8');
  stream.on('data', (chunk: string) => {
    buffered += chunk;
    const lines = buffered.split('\n');
    buffered = lines.pop() ?? '';
    for (const line of lines) handle(line.trimEnd());
  });
}

class SidecarSupervisor implements Sidecar {
  private child: ChildProcess | null = null;
  private port = 0;
  private stopping = false;
  private restartTimestamps: number[] = [];

  constructor(
    readonly secret: string,
    private readonly options: SidecarOptions,
  ) {}

  get baseUrl(): string {
    return `http://${HOST}:${this.port}`;
  }

  async start(): Promise<void> {
    this.options.onPhase?.('starting');
    const { command, args, cwd } = resolveLaunchCommand();

    if (!existsSync(command)) {
      this.options.onPhase?.('failed');
      throw new SidecarStartError(
        'service_missing',
        `The service executable is not where it should be: ${command}`,
      );
    }

    this.port = await this.spawnAndHandshake(command, args, cwd);
    await this.waitUntilAnswering();
    this.options.onPhase?.('ready');
  }

  private spawnAndHandshake(command: string, args: string[], cwd: string): Promise<number> {
    return new Promise((resolve, reject) => {
      const child = spawn(command, args, {
        cwd,
        // The secret travels in the environment, never in argv: a command line is readable by any
        // other process on the machine.
        env: {
          ...process.env,
          [SECRET_ENV_VAR]: this.secret,
          PYTHONUNBUFFERED: '1',
          SPECTRAPAINT_HARDWARE_PROFILE: this.options.hardwareProfile ?? 'cpu',
          SPECTRAPAINT_QUALITY_TIER: this.options.qualityTier ?? 'better',
        },
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
      });
      this.child = child;

      let settled = false;
      const settle = (finish: () => void) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        finish();
      };

const timer = setTimeout(() => {
         settle(() => {
           void killProcessTree(child);
reject(
              new SidecarStartError(
                'service_timeout',
                `The service did not announce a port within ${START_TIMEOUT_MS} ms.`,
              )
            );
         });
       }, START_TIMEOUT_MS);

      if (child.stdout) {
        onEachLine(child.stdout, (line) => {
          if (line.startsWith(HANDSHAKE_PREFIX)) {
            const announced = JSON.parse(line.slice(HANDSHAKE_PREFIX.length)) as { port: number };
            settle(() => resolve(announced.port));
            return;
          }
          if (line) console.log(`[service] ${line}`);
        });
      }
      // Never swallow it: quiet recovery without a log hides a recurring fault
      // (docs/conventions.md §5).
      if (child.stderr)
        onEachLine(child.stderr, (line) => line && console.warn(`[service] ${line}`));

child.once('error', (error) => {
         settle(() => reject(new SidecarStartError('service_exited', error.message)));
       });

       child.once('exit', (code, signal) => {
settle(() =>
            reject(
              new SidecarStartError(
                'service_exited',
                `The service exited during startup (code ${code}, signal ${signal}).`,
              ),
            )
          );
         this.handleUnexpectedExit(code, signal);
       });


     });
  }

  /**
   * Poll /health until it answers with the secret.
   *
   * The service listens before it announces its port, so this is a guard rather than the
   * mechanism — but a 200 here is also the only proof that the secret reached both sides intact,
   * which is why /health is authenticated.
   */
  private async waitUntilAnswering(): Promise<void> {
    const deadline = Date.now() + START_TIMEOUT_MS;

    while (Date.now() < deadline) {
      try {
        const response = await fetch(`${this.baseUrl}/health`, {
          headers: { Authorization: `Bearer ${this.secret}` },
        });
        if (response.ok) return;
        throw new SidecarStartError(
          'service_unreachable',
          `The service answered ${response.status} to an authenticated request.`,
        );
      } catch (error) {
        if (error instanceof SidecarStartError) throw error;
        await new Promise((wake) => setTimeout(wake, READY_POLL_INTERVAL_MS));
      }
    }

    throw new SidecarStartError('service_timeout', 'The service never became ready.');
  }

  /** Quiet restart on death, and a log line every time, so a recurring fault is not masked. */
  private handleUnexpectedExit(code: number | null, signal: NodeJS.Signals | null): void {
    if (this.stopping) return;

    const now = Date.now();
    this.restartTimestamps = this.restartTimestamps.filter((at) => now - at < RESTART_WINDOW_MS);

    if (this.restartTimestamps.length >= MAX_RESTARTS) {
      console.error(
        `[sidecar] died ${this.restartTimestamps.length} times in ${RESTART_WINDOW_MS / 1000}s; not restarting again`,
      );
      this.options.onPhase?.('failed');
      return;
    }

    this.restartTimestamps.push(now);
    console.warn(
      `[sidecar] died (code ${code}, signal ${signal}); restart ${this.restartTimestamps.length} of ${MAX_RESTARTS}`,
    );
    this.options.onPhase?.('restarting');

    void this.start().catch((error: unknown) => {
      console.error('[sidecar] restart failed:', error);
      this.options.onPhase?.('failed');
    });
  }

  async stop(): Promise<void> {
    this.stopping = true;
    if (this.child) {
      await killProcessTree(this.child);
      this.child = null;
    }
  }
}

export async function startSidecar(options: SidecarOptions = {}): Promise<Sidecar> {
  const supervisor = new SidecarSupervisor(generateLaunchSecret(), options);
  await supervisor.start();
  return supervisor;
}
