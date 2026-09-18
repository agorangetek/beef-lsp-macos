import * as vscode from "vscode";
import * as net from "net";
import { LanguageClient, LanguageClientOptions, ServerOptions, StreamInfo, TransportKind } from "vscode-languageclient/node";
import { registerCommands } from "./commands";
import { InitializedArgs } from "./types";
import { registerSettingsView } from "./settingsView";
import { registerTasks } from "./tasks";
import { execFile } from "child_process";

const devTcp = true;

export class Extension {
    private context: vscode.ExtensionContext;
    private client: LanguageClient;
    private initialized: boolean;

    private barItem: vscode.StatusBarItem;

    private configuration: string;

    constructor(context: vscode.ExtensionContext) {
        this.context = context;
        this.initialized = false;

        // Bar Item
        this.barItem = vscode.window.createStatusBarItem("beef-lsp", vscode.StatusBarAlignment.Left, 2);
        this.barItem.name = "Beef Lsp Status";
        this.barItem.command = "beeflang.changeConfiguration";

        // Register
        registerCommands(this);
        registerTasks(this);

        registerSettingsView(this, "workspace", false);
        registerSettingsView(this, "project", true);
    }

    start() {
        // TODO: Always use TCP transport since currently the STDIO one does not close properly
        // The server path is configurable because macOS GUI apps do not inherit the shell PATH,
        // so a launcher in ~/bin would otherwise never be found.
        const serverPath = vscode.workspace.getConfiguration("beeflang").get<string>("serverPath") || "BeefLsp";

        // Ask the OS for a free port instead of hardcoding 5556: two windows would otherwise
        // fight over the port, and a stale server from a previous window would block new ones.
        new Promise<number>((resolve, reject) => {
            const probe = net.createServer();
            probe.once("error", reject);
            probe.listen(0, "127.0.0.1", () => {
                const addr = probe.address();
                const port = addr && typeof addr === "object" ? addr.port : 0;
                probe.close(() => resolve(port));
            });
        }).then((port) => {
            const child = execFile(serverPath, [ `--port=${port}` ]);
            child.on("error", (err) => {
                vscode.window.showErrorMessage(
                    `Beef Lang: failed to start '${serverPath}' (${err.message}). ` +
                    `Set "beeflang.serverPath" to the full path of the BeefLsp executable.`);
            });

            let serverOptions: ServerOptions = { command: serverPath };

            // Retry the connect instead of a single 1s delay: the server needs time to start,
            // and failing here used to send the client into a crash/restart loop.
            serverOptions = () => new Promise<StreamInfo>((resolve, reject) => {
                const attempt = (n: number) => {
                    const socket = net.createConnection({
                        // Explicit IPv4 loopback: the server binds 127.0.0.1, avoiding clients
                        // that would try ::1 first.
                        host: "127.0.0.1",
                        port
                    });

                    socket.once("connect", () => {
                        const result: StreamInfo = { writer: socket, reader: socket };
                        resolve(result);
                    });
                    socket.once("error", (err) => {
                        socket.destroy();
                        if (n >= 100) reject(err); // ~10s of retries
                        else setTimeout(() => attempt(n + 1), 100);
                    });
                };
                attempt(0);
            });

            const clientOptions: LanguageClientOptions = {
                documentSelector: [{ scheme: "file", language: "bf" }]
            };

            this.client = new LanguageClient(
                "beeflang",
                "Beef Lang",
                serverOptions,
                clientOptions
            );

            this.setBarItem("Starting", true);
            this.barItem.show();

            this.client.start().then(this.onReady.bind(this));
        }).catch((err) => {
            vscode.window.showErrorMessage(`Beef Lang: could not find a free port: ${err}`);
        });
    }

    private onReady() {
        this.client.onNotification("beef/initialized", (args: InitializedArgs) => {
            this.setConfiguration(args.configuration);
            vscode.commands.executeCommand("setContext", "beef.isActive", true);

            this.initialized = true;
        });
    
        this.client.onNotification("beef/classifyBegin", () => this.setBarItem("Classifying", true));
        this.client.onNotification("beef/classifyEnd", () => this.setBarItem("Running", false));

        // Send settings
        this.client.sendNotification("beef/settings", {
            debugLogging: vscode.workspace.getConfiguration("beeflang").get<boolean>("debugLogging")
        });
    }

    setBarItem(status: string, spin: boolean) {
        this.barItem.text = "$(" + (spin ? "loading~spin" : "check") + ") Beef Lsp";
        this.barItem.tooltip = "Status: " + status;
    
        if (this.configuration !== undefined) this.barItem.text += ": " + this.configuration;
    }

    setConfiguration(configuration: string) {
        this.configuration = configuration;
        
        if (this.barItem.text.includes(":")) this.barItem.text = this.barItem.text.substring(0, this.barItem.text.indexOf(":")) + ": " + configuration;
        else this.barItem.text += ": " + configuration;
    }

    getConfigurations(): Promise<string[]> {
        return this.onlyIfRunningPromise(() => this.sendLspRequest<string[]>("beef/configurations"));
    }

    sendLspRequest<T>(method: string, param?: any): Promise<T> {
        return this.onlyIfRunningPromise(() => this.client.sendRequest<T>(method, param));
    }

    sendLspNotification(method: string, param: any) {
        this.onlyIfRunning(() => this.client.sendNotification(method, param));
    }

    registerCommand(command: string, callback: (ext: Extension) => void, onlyIfRunning = true) {
        this.context.subscriptions.push(vscode.commands.registerCommand(command, () => {
            if (onlyIfRunning) this.onlyIfRunning(() => callback(this));
            else callback(this);
        }, this));
    }

    disposable(disposable: vscode.Disposable) {
        this.context.subscriptions.push(disposable);
    }

    private onlyIfRunning(callback: () => void) {
        if (this.initialized && this.client.isRunning()) callback.bind(this)();
        else vscode.window.showInformationMessage("Beef LSP server is not running");
    }

    private onlyIfRunningPromise<T>(callback: () => Promise<T>): Promise<T> {
        if (this.initialized && this.client.isRunning()) return callback.bind(this)();

        vscode.window.showInformationMessage("Beef LSP server is not running");
        return Promise.reject("Beef LSP server is not running");
    }

    uri(...pathSegments: string[]): vscode.Uri {
        return vscode.Uri.joinPath(this.context.extensionUri, ...pathSegments);
    }

    async stop() {
        if (this.client && this.client.isRunning()) {
            await this.client.dispose();
        }

        this.barItem.hide();
        this.initialized = false;
    }
}

let extension: Extension;

export function activate(context: vscode.ExtensionContext) {
    extension = new Extension(context);
    extension.start();
}

export async function deactivate() {
    await extension.stop();
}