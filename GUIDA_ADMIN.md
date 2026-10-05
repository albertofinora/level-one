# Level One – Guida per l'admin

Questa guida copre la configurazione iniziale (una volta sola), la gestione dei periodi e la sicurezza.

I nomi di menu e pulsanti di Google Cloud, GitHub e Streamlit sono quelli che conosco al momento in cui scrivo e potrebbero essere cambiati. Se qualcosa non corrisponde, cerca la voce con un nome simile, oppure consulta la documentazione ufficiale del servizio.

---

## 1. Cosa c'è nel progetto

| File | A cosa serve |
|---|---|
| `app.py` | L'app: schermate, moduli, grafici |
| `logic.py` | Calcoli: voti, statistiche, PIN |
| `storage.py` | Lettura e scrittura su Google Sheets (o su file CSV quando la provi in locale) |
| `hltb.py` | Ricerca dei dati su HowLongToBeat |
| `seed.py` | Dati iniziali presi dal foglio Level One |
| `GUIDA_MEMBRI.md` | Guida mostrata ai membri dentro l'app |
| `requirements.txt` | Pacchetti Python necessari |
| `.streamlit/config.toml` | Colori dell'app |
| `.streamlit/secrets.toml.example` | Modello per password e credenziali |
| `.gitignore` | Impedisce di caricare su GitHub secrets e chiavi |

---

## 2. Configurazione iniziale

### A. Il foglio Google

1. Crea un foglio Google vuoto, per esempio "Level One – dati".
2. Copia il suo **ID** dall'indirizzo: è la parte tra `/d/` e `/edit`.
   `https://docs.google.com/spreadsheets/d/`**`QUESTO-È-L-ID`**`/edit`
3. Non creare tab né intestazioni: ci pensa l'app al primo avvio.

### B. L'account di servizio Google

L'account di servizio è un utente "robot" che può leggere e scrivere **solo** i fogli che condividi con lui.

1. Vai su Google Cloud Console e crea un nuovo progetto, per esempio `level-one`.
2. Nella libreria delle API abilita la **Google Sheets API**. Se in seguito vedi un errore che nomina la Google Drive API, abilita anche quella.
3. In *IAM e amministrazione → Account di servizio* crea un account di servizio. Non servono ruoli sul progetto.
4. Apri l'account appena creato, vai su *Chiavi → Aggiungi chiave → Crea nuova chiave → JSON*. Si scarica un file `.json`.
5. **Tratta quel file come una password**: non inviarlo in chat e non caricarlo su GitHub.
6. Nel file trovi `client_email` (qualcosa come `nome@progetto.iam.gserviceaccount.com`). Condividi il foglio del punto A con quell'indirizzo, come **Editor**.

Per quanto ne so, creare il progetto e l'account di servizio non richiede un metodo di pagamento, ma verificalo quando lo configuri. Le API di Sheets sono gratuite entro i limiti di richieste al minuto, e un club di 10 persone ne resta molto al di sotto.

### C. Il repository GitHub

1. Crea un repository **pubblico**, per esempio `level-one`. Se preferisci non collegare Streamlit al tuo account principale, crea un account GitHub dedicato.
2. Carica tutti i file del progetto, cartella `.streamlit` compresa.
3. Controlla che **non** ci siano `secrets.toml` né file `.json`. Il `.gitignore` li esclude, ma se carichi i file dal sito di GitHub trascinandoli, il `.gitignore` non ti protegge: verifica a occhio.

Il codice è pubblico, ma i dati no: stanno nel foglio Google, e le credenziali nei secrets di Streamlit.

### D. Pubblicazione su Streamlit Community Cloud

1. Entra su Streamlit Community Cloud con l'account GitHub del punto C.
2. Crea una nuova app: scegli il repository, il ramo (`main`) e il file `app.py`. Puoi anche scegliere l'indirizzo, per esempio `levelone-club`.
3. Prima di pubblicare apri le **impostazioni avanzate → Secrets** e incolla il contenuto di `secrets.toml.example`, compilato così:
   - `admin_password`: una password lunga, solo tua.
   - `pin_pepper`: una stringa casuale lunga. **Non cambiarla più**: se la cambi, tutti i PIN smettono di funzionare.
   - `sheet_id`: l'ID del punto A.
   - la sezione `[gcp_service_account]`: copia ogni campo dal file `.json`. Per `private_key` copia l'intera riga così com'è nel JSON, con i `\n` dentro e tra virgolette.
4. Pubblica. Il primo avvio richiede un paio di minuti.

I secrets si possono modificare anche dopo, dalle impostazioni dell'app.

### E. Primo avvio

1. Apri l'app. Vedrai il messaggio che non ci sono membri.
2. Apri **Area admin**, inserisci la password, vai su **Dati → Importa dati iniziali**. Vengono creati:
   - i 10 membri (Ventu, Bubu, Rick, Scand, Dalla, Fede, Marty, Luca, Stefano, Denise);
   - i 10 giochi del foglio originale;
   - il **periodo 1** (proposto da Ventu il 16/06/2026, vincitore Hellblade), in stato *In gioco*;
   - il **periodo 2** con le proposte di Bubu, in stato *Bozza*.
3. Vai su **Giochi** e controlla i generi. Quelli iniziali li ho assegnati io come prima proposta, quindi verificali. *Regions of Ruin* non ha tag perché non ne ero sicuro.
4. Nel foglio originale mancano i voti sulle proposte del periodo 1, quindi quel periodo non ha voti registrati. Le statistiche su proponenti e desiderati cominciano a essere utili dal periodo 2.

### F. Condividi il link

Manda il link ai membri insieme alla guida (che trovano anche dentro l'app, nella scheda **Guida**).

---

## 3. Provarla sul tuo computer (facoltativo)

```bash
pip install -r requirements.txt
streamlit run app.py
```

Senza `.streamlit/secrets.toml` l'app parte in **modalità locale**: i dati finiscono in file CSV nella cartella `data/` e la password admin è `admin`. Comodo per fare prove senza toccare il foglio vero.

Per collegarla al foglio anche in locale, copia `secrets.toml.example` in `.streamlit/secrets.toml` e compilalo.

---

## 4. Gestire un periodo

Tutto si fa da **Admin → Periodi**.

1. **Crea il periodo.** Da *Nuovo periodo* scegli il proponente, la data e fino a 5 giochi. Se un gioco non c'è ancora, aggiungilo prima da **Giochi**. Puoi partire in *Bozza*, se vuoi ricontrollare le opzioni, oppure aprire subito la votazione.
2. **Apri la votazione.** Dalla bozza premi *Apri votazione*.
3. **Segui chi manca.** Nel riquadro del periodo vedi quanti hanno votato e i nomi di chi manca. Tu vedi anche i conteggi parziali, i membri no.
4. **Chiudi la votazione.** Se c'è un solo primo classificato, è già selezionato come vincitore. Conferma con *Chiudi votazione e conferma il vincitore*. Il periodo passa a *In gioco*: i membri possono dare l'hype e poi valutare.
5. **Chiudi il periodo.** Quando hanno valutato tutti (vedi chi manca nel riquadro), premi *Chiudi il periodo*. Da quel momento le valutazioni non si possono più modificare.
6. **Rivela i voti alla serata.** Finché non premi *Rivela i voti a tutti*, ogni membro vede solo i propri voti. Le valutazioni di quel periodo sono escluse da Storico e Statistiche, e l'app mostra solo quanti hanno già valutato. Alla serata premi il pulsante e tutto compare per tutti. L'hype fa eccezione: è visibile a tutti già da quando il periodo passa a *In gioco*.

Tu, come admin, vedi sempre tutto, anche quando i voti sono nascosti ai membri:
- nel riquadro di ogni periodo, **Chi ha votato cosa** mostra le scelte di ciascuno sulle proposte;
- **Valutazioni di ogni membro** mostra hype, FINAL, categorie, ore, il peso di chi ha abbandonato e, sotto la tabella, i commenti;
- nelle **Statistiche**, dopo essere entrato nell'area admin, compare l'interruttore *Includi i voti nascosti*, che vale solo per te.

Ti consiglio di chiudere il periodo **prima** di rivelare, così nessuno può cambiare il voto dopo aver visto quelli degli altri. L'app però non lo impone: se rivelare prima ti fa comodo, puoi farlo.

Puoi avere contemporaneamente un periodo *In gioco* e la votazione del successivo aperta.

### Pareggi

Le regole non sono ancora definite. Per ora, in caso di parità, l'app mostra un avviso con i giochi a pari merito e non preseleziona nessun vincitore: lo scegli tu. Quando il club avrà deciso una regola, si potrà automatizzare.

### Correzioni

Ogni periodo ha un pulsante **Correzioni** che permette di rimettere un periodo in qualunque stato, per esempio riaprire le valutazioni di un periodo chiuso per errore. Cambiare stato non cancella voti né valutazioni. Da lì puoi anche **nascondere di nuovo** i voti rivelati per errore.

---

## 5. Giochi, piattaforme e HowLongToBeat

Da **Admin → Giochi** aggiungi o modifichi un gioco. In fondo trovi il database dei giochi, con gli stessi filtri e le stesse schede della scheda Giochi dei membri. Solo qui, però, la sottoscheda *Nel club* mostra anche le valutazioni non ancora rivelate. Generi e piattaforme sono tag: scegli tra quelli esistenti o scrivine di nuovi. I membri li usano come filtri nella scheda **Giochi**.

**Presentazione senza spoiler.** Nel modulo c'è il campo **Sinossi**: due o tre frasi scritte a mano (massimo 800 caratteri). Compare ai membri sopra la votazione, nella sezione *Di cosa parlano?*, e nella sottoscheda *Info* del gioco. Accanto, l'app aggiunge da sola i link a HowLongToBeat, a una ricerca su Steam (solo se tra le piattaforme c'è PC o se non ce n'è nessuna) e a una ricerca del trailer su YouTube.

**Dati da HowLongToBeat.** Sopra il modulo c'è la ricerca: scrivi il titolo (in inglese di solito funziona meglio), premi *Cerca*, scegli il risultato giusto e premi *Usa questo risultato*. L'app compila anno, piattaforme, le tre durate (storia, storia + extra, completista) e il link alla pagina del gioco. Poi prova a leggere i **generi** dalla pagina del gioco e li aggiunge a quelli già scelti, convertiti nelle etichette del club (per esempio Role-Playing → RPG, Adventure → Avventura, First-Person + Shooter → FPS). Le prospettive come Third-Person o Side-Scrolling vengono scartate, mentre i generi senza conversione restano in inglese. I generi trovati compaiono direttamente nel campo *Generi* del modulo. Tutto resta modificabile prima di salvare.

**Completare i giochi già inseriti.** Da **Admin → Dati → Completa i dati mancanti** l'app cerca in un colpo solo tutti i giochi senza dati HowLongToBeat, e aggiunge i generi a quelli che ne sono privi. I generi vengono solo aggiunti, mai tolti. Prende il risultato più simile al titolo; quando l'abbinamento è incerto non salva nulla e segna il gioco "da controllare a mano". Dopo, controlla gli abbinamenti nella tabella dei giochi, perché un titolo simile può corrispondere a un remake o a un seguito.

**Limiti da conoscere.** HowLongToBeat non offre un'API ufficiale: l'app usa una libreria non ufficiale (`howlongtobeatpy`) che legge i dati del sito. Se il sito cambia, la ricerca può smettere di funzionare finché la libreria non viene aggiornata; in quel caso l'app lo segnala e ti dà un link per cercare il gioco e copiare i dati a mano. È anche possibile che il sito blocchi le richieste dai server di Streamlit. Non ho verificato i termini d'uso di HowLongToBeat: per un uso occasionale come questo il rischio è basso, ma se ti interessa controllali sul loro sito.

La lettura dei generi è ancora più fragile, perché dipende dalla struttura della pagina del gioco e non è coperta dalla libreria. Non è stato possibile provarla sul sito vero. Se non funziona, i generi semplicemente non vengono aggiunti: il campo *Generi* resta come prima (nel completamento automatico lo segnala la colonna *Generi*). La tabella di conversione dei generi si trova in `hltb.py` (`GENERI`), se vuoi cambiare un'etichetta.

Se la libreria si rompe e viene aggiornata, per avere la versione nuova basta riavviare l'app dalla dashboard di Streamlit.

### Gestire i tag

Da **Admin → Tag** vedi tutti i generi (o, con l'interruttore in alto, tutte le piattaforme) con il numero di giochi che li usano. Scegli un tag per vedere quali giochi lo hanno, poi:
- **Rinomina** cambia il nome in tutti i giochi. Se scrivi il nome di un tag che esiste già, i due vengono **uniti** (utile per doppioni come "Rpg" e "RPG");
- **Elimina** toglie il tag da tutti i giochi, dopo una conferma. I giochi restano, perdono solo quel tag.

Un tag esiste finché almeno un gioco lo usa: dopo l'eliminazione sparisce anche dai menu dei filtri. Se però rileggi i generi da HowLongToBeat, un tag eliminato può ricomparire. In quel caso puoi cambiarne la conversione nella tabella `GENERI` in `hltb.py`.

## 6. Membri e PIN

Da **Admin → Membri** puoi:

- **aggiungere** un membro, che al primo accesso sceglierà il suo PIN;
- **rinominare** un membro, e i suoi voti restano collegati;
- **disattivare** chi lascia il club: non compare più nell'accesso e non conta tra i votanti, ma i suoi voti restano nelle statistiche;
- **azzerare il PIN** di chi l'ha dimenticato, o di un profilo che qualcun altro ha "occupato" per primo.

---

## 7. Il foglio Google: come è organizzato

Ogni tab è una tabella.

- Modificate solo dall'admin, tramite l'app: `membri`, `giochi`, `periodi`. In `giochi` generi e piattaforme sono separati da `;`. In `periodi` la colonna `rivelato` vale `1` quando i voti sono stati rivelati, ed è vuota quando sono nascosti.
- Scritte dai membri: `pin`, `voti_proposte`, `hype`, `valutazioni`. In queste **ogni invio aggiunge una riga e conta l'ultima riga** di ciascun membro per ciascun periodo. Così due persone che votano nello stesso istante non si cancellano a vicenda.

Se devi correggere a mano nel foglio:

- non modificare le colonne `*_id`, che collegano le tabelle tra loro;
- non riordinare le righe delle tabelle scritte dai membri, perché l'ordine decide qual è l'ultima;
- scrivi i decimali con il punto (`7.5`), non con la virgola;
- dopo una modifica a mano usa **Admin → Dati → Ricarica i dati dal foglio**, altrimenti l'app può mostrare i dati vecchi per circa un minuto.

---

## 8. Backup

- **Admin → Dati → Scarica tutti i dati** produce uno ZIP con un CSV per tabella. Scaricalo ogni tanto, per esempio a fine periodo.
- Il foglio Google conserva anche la sua cronologia delle versioni, utile se qualcosa va storto.

---

## 9. Sicurezza: cosa tenere segreto

| Cosa | Dove sta | Se esce… |
|---|---|---|
| File `.json` della chiave | Solo sul tuo PC (e nei secrets) | Chi lo ha può leggere e scrivere il foglio. Elimina la chiave da Google Cloud, creane una nuova e aggiorna i secrets |
| `admin_password` | Secrets | Chi la ha può gestire l'app. Cambiala nei secrets |
| `pin_pepper` | Secrets | Il foglio da solo non basta a indovinare i PIN, ma con il pepper sì. Se lo cambi, azzera i PIN di tutti |

Limiti da conoscere:

- Dopo l'accesso il browser tiene un cookie firmato che vale 30 minuti dall'ultima azione (`SESSIONE_MINUTI` in `app.py`). Vale anche per l'area admin. Il cookie smette di valere se premi *Esci*, se azzeri il PIN di quella persona o se cambi `admin_password` o `pin_pepper`. Chi usa un dispositivo condiviso deve premere *Esci*.
- Il PIN a 4 cifre basta tra amici, ma non è una protezione forte. Il blocco dopo 5 tentativi vale per la singola sessione del browser: chi ricarica la pagina può riprovare.
- I PIN nel foglio sono salvati cifrati, mai in chiaro.
- Nel foglio salva solo soprannomi: niente email, telefoni o cognomi.

---

## 10. Limiti noti di questa prima versione

- L'app non ricorda l'accesso dopo che si chiude la pagina: il PIN va reinserito a ogni visita.
- Se l'app non riceve visite per 12 ore va in letargo: il primo che la apre preme il pulsante per risvegliarla e aspetta qualche secondo.
- Le regole per i pareggi sono ancora da definire.
- I voti nascosti sono nascosti **nell'app**. Chi ha accesso al foglio Google, cioè tu, li vede comunque: se vuoi goderti la sorpresa, non aprirlo prima della serata.
- Il periodo 1 non ha voti sulle proposte, perché non erano nel foglio originale.

---

## 11. Problemi comuni

- **"Impossibile leggere i dati"** all'avvio: controlla nei secrets `sheet_id` e i campi di `[gcp_service_account]`, e che il foglio sia condiviso come Editor con il `client_email`.
- **Errore che nomina un'API non abilitata**: abilita quell'API nel progetto Google Cloud e riavvia l'app dalle impostazioni di Streamlit.
- **Errore sulla `private_key`**: di solito mancano le virgolette o i `\n`. Ricopiala dal file `.json` così com'è.
- **"Troppe richieste"**: raro con 10 persone. Aspetta un minuto e riprova.
- **Un membro dice che il PIN non funziona**: azzeralo da *Membri* e fagliene scegliere uno nuovo.
