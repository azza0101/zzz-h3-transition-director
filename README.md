# ZZZ H3 Transition Director (ComfyUI, MiniMax H3)

Transizioni generate con MiniMax H3 tra due clip (A -> B) su una timeline: zona automatica (short/medium/large), stadi automatici a frazioni, mai tagli se non chiesti, ancora B automatica, prompt automatico, fps originali, video verticali.

**Per un agente (MCP) su un altro PC: leggere e seguire `COME_USARE_PER_AGENTI.md`, sezione 9 "INSTALLAZIONE SU UN ALTRO PC" e sezione 0 "USO RAPIDO".**

- Installare: `git clone https://github.com/azza0101/zzz-h3-transition-director` dentro `ComfyUI/custom_nodes/` (repository privato: serve `gh auth login` con l'account proprietario).
- Aggiornare: `git pull` nella cartella del nodo, poi riavvio di ComfyUI e F5 nel browser. La versione e' nel titolo del nodo e in testa a `director.py`.
- Workflow pronto: `example_workflows/` (compare nei Template di ComfyUI).
