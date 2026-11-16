# ZZZ H3 Transition Director — guida per agenti (MCP / assistenti)

Versione del nodo: **v2.16** (il numero e' nel titolo del nodo e nella prima riga del report; storico in testa a `director.py`).
Workflow di riferimento: `zzz_H3_TRANSITION_DIRECTOR_v2_TaoMate4`.

> Stato di validazione (2026-11-16, transizione telo verde -> treno, 117 frame, 24 fps, stesso seed):
> - v2.1/v2.3 con prompt manuale: identica alla run buona precedente.
> - **Prompt automatico (v2.2)**: funziona, esce una transizione quasi uguale (stesso arrivo sul treno). Differenza vista nel contact sheet: il treno compare un po' prima durante la caduta del telo e a terra resta meno stoffa. Valutato su 20 frame, non su ogni frame; audio non ascoltato. Limiti: la caption di A e' generica e dice "camera stationary" (puo' stridere con un segmento di camera), non coglie parlato/labbra ne' il telo a terra: questi vanno in `idea_transizione` o nei segmenti.
> - **Ricampionamento fps (v2.3)**: la funzione e' testata (conteggio frame/durata) ma con A a 24 fps e' un passaggio nullo; non ancora provata su una clip a 25/30 fps.

## 0. USO RAPIDO (v2.12) — cosa si scrive, cosa fa da solo

**Si fa a mano (utente o agente):**
1. Caricare A e B (schede Load video in cima alla timeline) e metterli sulla timeline: attaccati, sovrapposti o distanti. Il modo si calcola da solo; piu' distanti = piu' strada da generare.
2. (facoltativo) Una riga nel GLOBAL PROMPT (`idea_transizione`, con `automatico` acceso).
3. Pochi segmenti di prompt sulla timeline, uno per ogni cosa che succede: il CAMBIAMENTO (es. "il telo cade e rivela il treno"), l'AZIONE del soggetto, la CAMERA. Non serve spezzarli a mano.
4. Le scritte esatte che devono comparire (es. `'ETR 1000'` sul treno) vanno nel testo: H3 le inventa se non le vede.

**Fa da solo il Director:**
- **Transition zone** (`transition_zone`, visibile sul nodo, v2.15): `short` = 24 fr + buco (max 64), `medium` = 64 + buco (max 100), `large` = 96 + buco (max 131, al limite della finestra H3). Tetto per livello: short 35%, medium 55%, large 80% della durata di A + B (clip corte = zona corta, ma i tre livelli restano diversi); `zona_minima` resta un minimo assoluto. La config "perfetta" (buco 33 fr, zona ~124) corrisponde a `large`.
- **Zona automatica** (`zona_automatica`, default ON): la parte generata e' lunga 96 frame + il buco tra A e B, fino a 124 (vicino al limite della finestra H3). `zona_minima` resta solo un minimo. Se le clip sono corte scende a passi e lo scrive nel report.
- **Segmenti legati alla zona**: la timeline salva `zone: [z0, z1]`; se la zona cambia (clip spostate/rifilate) i segmenti si ridistribuiscono in proporzione (GUI e Director). Un agente che riscrive `timeline_data` con tempi nuovi deve **togliere `zone`** o aggiornarla alla zona nuova, altrimenti i suoi tempi vengono riproporzionati.
- **Stadi automatici** (`stadi_automatici`, default ON): ogni segmento >= 24 frame (1 s) diventa 2-4 stadi uguali con l'avanzamento scritto ("about one quarter / half / three quarters complete" -> "now complete, final state fully reached and holds steady"). E' la chiave della gradualita' (vedi sez. 6). Stadi propri: separarli con `->` nel testo ("crepe -> buchi -> pareti a terra"), distribuiti in parti uguali. Un segmento da lasciare intero: `"stadi": false`.
- **Mai tagli** se non chiesti, **riempimento** dei tratti senza segmento, **ritmo costante**, **ancora B automatica** (frame di B dopo la zona, peso 0.15 -> 1), **prompt automatico** da A e B, **fps originali** in uscita.
- Sfumatura verso B 8 frame (non 16: con 16 gli ultimi frame "recuperano" verso B).

**Regola di scrittura (misurata):** descrivere SEMPRE in POSITIVO cosa compare e dove ("la parte alta mostra il cielo nero e il treno"), mai negazioni di posizione ("niente in alto"): la frase negativa ha prodotto una fascia di green in alto.

**Config di riferimento "perfetta"** (utente, 2026-11-16, h3_director_v2_00016): `timeline_PERFETTA_00016_20261116.json` nella cartella del nodo.

## 1. A cosa serve

Dati due clip (A prima, B dopo) il Director fa generare a MiniMax H3 il pezzo di raccordo tra i due: la timeline e' a **24 fps** (quelli di H3).
Modi, scelti dalla posizione dei clip sulla timeline:

| Modo | Quando | Cosa succede |
|---|---|---|
| sovrapposta | B si sovrappone ad A | la zona sovrapposta viene rigenerata (A che diventa B) |
| ponte | B e' lontana da A | il buco viene generato da zero |
| taglio | B attaccata ad A | raccordo a cavallo del taglio, durata = A + B |

Il modo si **calcola da solo** dalle posizioni dei clip (`b.pos` rispetto alla fine di A): non esistono piu' i bottoni "sovrapponi / attacca / stacca". Nella GUI c'e' un solo bottone **Snap ON/OFF** (come nel Dialogue Director): con snap acceso i bordi vicini si agganciano (B attaccata ad A = taglio); sovrapposta o lontana, il modo e la zona li risolve il codice. Lo stato e' in `timeline_data.snap_enabled` (`false` = snap spento). Un agente che scrive `timeline_data` direttamente sceglie il modo solo con `b.pos`: `pos` = fine di A -> taglio, minore -> sovrapposta, maggiore -> ponte.

Se la zona e' piu' corta di `zona_minima` si allarga a cavallo del raccordo. La griglia di H3 (contesto, lunghezza 17k+5, bordi dei token) la risolve il codice: **non calcolarla a mano**.

## 2. Catena del workflow (nodi principali)

Modello: `UNETLoader (H3 ref2va)` -> LoRA acceleratrice (TaoMate 3 step) -> `ModelAttentionBackend` -> (SLA, bypass) -> anteprima taeh3 -> `MiniMaxH3SigmaShift` (12 / 3) -> (Peso Ancore, bypass) -> sampler.
Ingressi: `CLIPLoader`, `VAELoader` video, VAE audio, VAE TRT decoder (decode piu' veloce).
**Director** (`zzz_H3_TransitionDirector`): carica i due video da solo (`video_a`, `video_b`), costruisce prompt, latente, maschera e `plan`.
Sampler: `RandomNoise` (seed), `KSamplerSelect` (euler), `ManualSigmas` (`1.0, 0.961165, 0.853333, 0.0` = 3 step TaoMate), dentro il subgraph di generazione.
**Assemble** (`zzz_H3_TransitionDirectorAssemble`): rimonta frame veri + parte generata, audio originale in dissolvenza; esce a fps di A (`fps_uscita`).
Uscite: due `VHS_VideoCombine` (nvenc veloce e H.264 crf 10).

L'audio e i frame reali li legge **il Director** (ffmpeg): non servono loader video esterni ne' nodi audio a parte.
"Scheduler + Steps" e "DURATA TRANSIZIONE" sono nodi residui: la durata la decide la zona sulla timeline, le sigma arrivano da `ManualSigmas`.

## 3. Campi del Director

- `video_a`, `video_b`: file in `input/` (anche sottocartelle).
- **Caricare i video (GUI, v2.5):** in cima alla timeline ci sono due schede (A e B) con anteprima, nome, durata, fps, risoluzione, audio e il bottone **Load video** (upload dal PC) piu' un elenco dei video gia' in `input/`. I combo `video_a` / `video_b` sono nascosti ma restano i campi veri: un agente li imposta con `panel_set_widget` (nome file relativo a `input/`).
- `idea_transizione` appare nella GUI col titolo **GLOBAL PROMPT** (solo con `automatico` acceso).
- `megapixel` (1.03 = tela ufficiale di H3, 768x1344), `crop` (center/stretch).
- `contesto` (13): frame veri che H3 vede prima e dopo la zona. `zona_minima` (63).

### Parametri NASCOSTI nella GUI (esistono per un agente, se servono)
Dalla v2.4 non si vedono sul nodo ma restano campi reali: si leggono/scrivono con `panel_query_graph` / `panel_set_widget` sul nodo Director. **Non sono calcolati dalla timeline**: sono valori fissi con i default approvati, tenerli cosi' salvo motivo.
- `sfuma_A_dentro`, `sfuma_A_fuori`, `sfuma_B_dentro`, `sfuma_B_fuori` (frame, default **8 / 0 / 16 / 8**) e `curva_sfumatura` (`smooth` | `lineare`): come la maschera sfuma ai bordi della zona rigenerata. Piu' alti = raccordo piu' morbido ma H3 ha meno liberta' vicino ai clip; `fuori` allarga la sfumatura verso l'esterno della zona.
- `oltre_limite_H3` (default **True**, sempre acceso): sblocca una tela oltre quella ufficiale di H3 (1.03 MP, 768x1344) fino a 4 MP. E' fuori dall'addestramento: rischio di ripetizioni/incoerenze, piu' tempo e VRAM. Con `megapixel` = 1.03 non cambia nulla; conta solo se si alza `megapixel`, quindi **non alzare `megapixel` oltre 1.03 senza dirlo all'utente**.
- **Prompt manuale** (`automatico` spento): `scena` (descrizione generale, in testa), segmenti della timeline, `finale` (frase in coda con "flowing straight into the next shot"), `overall_soundscape`, `non_diegetic_music`.
- **Prompt automatico** (`automatico` acceso, v2.2): descrive A e l'inizio di B con Qwen3-VL-2B locale (in cache), scrive raccordo e audio da solo. Si scrive solo `idea_transizione` (una riga, correzioni comprese) e i segmenti. Il report contiene il prompt completo: leggerlo.
- `timeline_data`: JSON **nascosto** nel widget (vedi sotto).

## 4. `timeline_data` (si edita come testo, la GUI e' un DOM non cliccabile da un agente)

```json
{"a":{"in":120,"out":179,"pos":0},
 "b":{"in":14,"out":72,"pos":59},
 "anchors":[{"id":"bB","frame":90,"image":"zzz_h3td_ancore/<file>.png","peso_prima":0.15,"peso":1}],
 "prompts":[{"id":"p1","start":28,"end":49,"text":"..."}]}
```
- `in`/`out`: frame (a 24 fps timeline) del file sorgente; `pos`: dove parte il clip sulla timeline.
- **Ancora B automatica (v2.9, `ancora_B_automatica`, default True)**: due tipi di ancora, da non confondere. L'automatica la calcola il Director: il frame di **B subito dopo la zona** (`z1`), messo a `z1 - 1`, con peso `0.15 -> 1` (curva dall'inizio della finestra, cioe' sopra A, fino al frame dell'ancora). Non sta in `timeline_data` e non si modifica: si ricalcola da sola se si spostano A, B o la zona. E' il "contesto di B" della config approvata (prima era un'ancora manuale a f90 con il frame 46 di B). **Non aggiungere a mano una seconda ancora uguale** nella lista. Nella timeline si vede come rombo vuoto arancione "auto · contesto B".
- Le ancore **manuali** (lista `anchors`) sono i keyframe ad hoc dell'utente (immagine da file o frame preso con FRAME RIFERIMENTO TRANSIZIONE).
- `anchors` (v2.8): se hanno `clip` ("a"/"b") e `src` (frame sorgente) **seguono il clip**: il frame di timeline e' `clip.pos + (src - clip.in)` e si ricalcola da solo quando il clip si sposta o si rifila (sia nella GUI che nel Director). Il bottone FRAME RIFERIMENTO TRANSIZIONE li crea cosi'; le ancore vecchie si riconoscono dal nome file `<video>_f<frame>_<hash>.png`. Un'ancora senza `clip`/`src` (da file) resta al frame scritto. Nota: spesso e' il frame di B che entra subito dopo la zona, cioe' un contesto di B in piu' per H3; i pesi (`peso_prima`/`peso`) agiscono solo se il nodo "PESO ANCORE" non e' in bypass.
- `anchors`: immagine guida a un frame della timeline (le immagini stanno in `input/zzz_h3td_ancore/`, create dalla GUI o dalla rotta di grab).
- `prompts`: segmenti `start`..`end` in frame di timeline. **Minimo 12 frame (0.5 s)**: sotto H3 non rispetta il segmento. I segmenti possono sovrapporsi (utile per un segmento "camera" sopra uno "azione").
- Scrivere il JSON con `panel_set_widget` sul widget `timeline_data`, poi rileggere con `panel_query_graph` (fields detail). La GUI si riallinea da sola.

## 5. Come si lavora: "l'utente descrive la transizione, l'agente sistema"

Ciclo usato finora, da ripetere:

1. `panel_graph_outline`: leggere la canvas e **i modi dei nodi** (alcuni sono in bypass di proposito: SLA, Peso Ancore, accelerazione v4). Non cambiarli senza motivo.
2. L'utente dice come vuole la transizione (a parole). Tradurla in: zona sulla timeline (`pos`/`in`/`out`), segmenti di prompt per fase, eventuale ancora sul frame d'arrivo.
3. **Una modifica per volta**, stesso `noise_seed` (nodo Seed, `fixed`), per capire cosa ha causato cosa.
4. `panel_run`, poi **guardare l'uscita**: contact sheet, e **ogni frame** nei punti critici (inizio, momento della trasformazione, arrivo). Le metriche non vedono il realismo.
5. Se qualcosa non va: correggere il **prompt del segmento** responsabile (vedi regole), non il modello. Rilanciare e confrontare con la run buona precedente.
6. Quando una configurazione e' buona, **non romperla**: le varianti si provano come opzioni spente / con un seed in piu', e si torna subito al buono.

## 6. Regole di prompt apprese (transizione telo verde -> treno)

- Descrivere **cosa e' davanti e cosa dietro** esplicitamente. "Dietro X" da solo non crea occlusione: dire quale layer sta davanti.
- Dare lo **stato finale** della scena fin dal primo frame in cui compare: "porta gia' spalancata", "banchina scura, solo luce dai finestrini", "nessun binario visibile".
- Cio' che non deve succedere va scritto come stato positivo: "il telo cade tutto in un pezzo e resta fermo in pieghe pesanti, nessun lembo sospeso o che svolazza".
- Luce coerente con la clip B ("exactly the same low light as the next shot"): altrimenti l'arrivo non si aggancia.
- Movimento di camera in un segmento separato e sovrapposto (es. 63-91) rispetto all'azione (60-75).
- Audio: dire che la voce continua identica per tutta la transizione, e cosa le si aggiunge sotto (rumore del telo, passi, ambiente).
- Un'ancora sul frame d'arrivo (`peso_prima` basso, `peso` 1) aiuta ad atterrare nell'inquadratura di B.

### Regola v2.10: MAI tagli se non chiesti espressamente (prompt automatico)
- Con `automatico` acceso il prompt dice sempre "ONE single uninterrupted take ... no cut, no jump cut, no scene change, no fade ... including the gap between the two clips" e il raccordo con B "reached by continuous motion with no cut".
- I **tratti della zona generata senza segmento di prompt** (>= 0.5 s) vengono riempiti da soli con "the action simply continues in the same single shot ... with no cut". Cosi' un gap grande tra A e B non resta senza istruzioni.
- Un taglio si ottiene solo scrivendolo nel GLOBAL PROMPT (`idea_transizione`) con una di queste parole: cut, hard cut, jump cut, taglio, stacco, stacchi. Allora le frasi anti-taglio non vengono aggiunte.
- Nota (2026-11-16): allontanare B non allunga la zona generata (resta `zona_minima`, 64 frame): H3 ha lo stesso tempo per fare piu' strada, e nelle prove senza queste frasi ha fatto un taglio netto campo largo -> primo piano. Per piu' camminata generata servono `zona_minima` piu' alta e segmenti proporzionati alla zona.

## 7. fps

H3 genera sempre a **24 fps**: non prenderli dai video. Il Director legge gli fps reali dei file (ffprobe) e porta tutto a 24; l'Assemble, con `fps_uscita = originale (fps di A)`, riporta l'uscita agli fps di A con ricampionamento temporale (frame piu' vicino se |fps-24| <= 1, altrimenti miscela lineare). Per un'interpolazione migliore serve un modello RIFE in `models/frame_interpolation` (oggi vuota).

## 8. Trappole

- Le modifiche al codice Python del nodo richiedono **riavvio di ComfyUI + F5**; il solo F5 non basta (i campi li definisce il backend).
- v2.12: `zona_automatica`/`stadi_automatici` sono stati inseriti PRIMA di `ancora_B_automatica`: nei workflow salvati prima, dopo F5 i valori scivolano (visto: `stadi_automatici` vuoto = stadi SPENTI). Dopo un aggiornamento controllare questi booleani con `panel_query_graph` e rimetterli a true. I campi nuovi vanno SEMPRE aggiunti in coda.
- Aggiungere widget **obbligatori** sposta `widgets_values` dei workflow salvati: i campi nuovi vanno come `optional` in coda, con default che non cambi il comportamento.
- Alzare `VERSION` in `director.py` a ogni modifica e annotarla; tenere un backup `director.py.backup_<versione>_<data>`.
- Non lasciare nodi bypassati "per sicurezza" nella versione da distribuire: SLA, Peso Ancore e LoRA v4 sono opzioni, il test ha funzionato senza.
- Dipendenze da portare su un altro PC: cartella `zzz_h3_transition_director`, modelli H3 (UNET fl2va, CLIP, VAE video/audio, LoRA TaoMate), engine TRT del decoder (opzionale), Qwen3-VL-2B in `models/LLM/Qwen-VL/` (solo per il prompt automatico), `ffmpeg`/`ffprobe` nel PATH, nodi VHS.

## 9. INSTALLAZIONE SU UN ALTRO PC (istruzioni per l'agente)

0. **Accesso:** il repository e' PRIVATO. Se `git clone` chiede credenziali: `gh auth login` (account dell'utente) e poi `gh repo clone azza0101/zzz-h3-transition-director`.
1. **Nodo:** `git clone <url di questo repository>` dentro `ComfyUI/custom_nodes/` (cartella `zzz_h3_transition_director`). Aggiornare: `git pull` + riavvio di ComfyUI + F5. Il workflow e' in `example_workflows/` e compare nei Template di ComfyUI sotto questo nodo.
2. **Prima di scaricare qualunque modello: CERCARE se c'e' gia'** sul PC (cartelle `models/` di ComfyUI e i percorsi in `extra_model_paths.yaml`), anche con nome diverso (stesso modello in altra quantizzazione). Scaricare SOLO cio' che manca, con il tool di download di ComfyUI (`download_model`), nella cartella giusta. Non inventare URL: cercare il nome esatto del file (HuggingFace / Civitai) e chiedere all'utente se non si trova.
3. **Modelli usati dal workflow: dove scaricarli** (indirizzi verificati il 2026-11-16, tutti rispondono; le dimensioni servono a riconoscere un file gia' presente). Cartella = sottocartella di `ComfyUI/models/`.

   | File | Cartella | Download | Dimensione |
   |---|---|---|---|
   | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | `diffusion_models/MINIMAX/` | https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors | 20 970 379 616 B (~21 GB) |
   | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `text_encoders/` | https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors | 15 687 142 551 B (~15.7 GB) |
   | `minimax_h3_video_vae_int8_convrot.safetensors` | `vae/` | https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_int8_convrot.safetensors | 2 811 065 184 B |
   | `minimax_h3_audio_vae_fp32.safetensors` | `vae/` | https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors | 605 254 808 B |
   | `minimax_h3_taomate_fl2va_3step_avg_rank_19_bf16.safetensors` (LoRA TaoMate 3 step, ATTIVA) | `loras/MINIMAX/` | https://huggingface.co/Kijai/MiniMax-H3-experimental/resolve/main/loras/minimax_h3_taomate_fl2va_3step_avg_rank_19_bf16.safetensors | 176 723 664 B (identica a quella usata qui) |
   | `taeh3.safetensors` (solo anteprima) | `vae_approx/` | https://huggingface.co/OzzyGT/taeh3/resolve/main/taeh3.safetensors (mirror di madebyollin/taehv) | 22 709 752 B (identica a quella usata qui) |
   | `Qwen3-VL-2B-Instruct` (cartella intera, solo per `automatico`) | `LLM/Qwen-VL/Qwen3-VL-2B-Instruct/` | https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct (scaricare tutto il repo, es. `hf download Qwen/Qwen3-VL-2B-Instruct --local-dir ...`) | ~4 GB |

   - Il text encoder **nvfp4** va al meglio sulle GPU NVIDIA **Blackwell (RTX 50xx)**; sulle altre e' emulato. Alternativa: `qwen3vl_32b_minimax_h3_int8_convrot.safetensors` (https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors, ~27 GB): in quel caso cambiare il file nel CLIPLoader "CLIP H3".
   - Esistono copie con lo stesso nome ma hash diverso (es. Abiray): usare gli indirizzi sopra.
   - `minimax_h3_vae_decoder.engine` (decoder TensorRT, OPZIONALE): **non si scarica e non si copia**, va compilato sulla GPU di destinazione (nota "DECODE VELOCE" nel workflow). Se manca, collegare il VAE video normale al decode.
   - Non servono: `zzz_minimax_h3_turbo_v4_step600_pruned208.safetensors` (nodo in bypass).
4. **Pacchetti di nodi richiesti:** ComfyUI recente con i nodi MiniMax H3 nativi (testato su 0.44), ComfyUI-VideoHelperSuite (VHS_VideoCombine), comfyui-kjnodes (anteprima taeh3), ComfyUI-H3VAE_TRT (solo per il decoder TensorRT). In bypass/inutilizzati, installarli solo se richiesti all'apertura: plaguekind ComfyUI-H3-SLA-Attention (SLA), zzz_ripple_long (PESO ANCORE), zzz_h3_transition_timing (DURATA TRANSIZIONE, residuo). Python: `transformers` (per Qwen3-VL) e `ffmpeg`/`ffprobe` nel PATH.
5. **Verifica dopo l'installazione:** riavviare ComfyUI, F5, aprire il workflow da `example_workflows/`, controllare con `panel_query_graph` sul nodo Director che `zona_automatica`, `stadi_automatici`, `ancora_B_automatica`, `automatico` siano true e `transition_zone` = medium; caricare due video e fare un run di prova. Se mancano nodi, installarli con il Manager; se mancano modelli, vedi punto 2-3.
6. **Aggiornamenti:** quando l'utente dice "cerca aggiornamenti del Transition Director": `git -C ComfyUI/custom_nodes/zzz_h3_transition_director pull`, leggere le righe nuove dello storico in testa a `director.py`, riavviare ComfyUI, F5, ripetere la verifica del punto 5 (i campi nuovi possono spostare i valori salvati: controllare i booleani).
7. **Avvio consigliato:** `--max-upload-size 4096` per caricare video grandi dal pulsante Load video.
