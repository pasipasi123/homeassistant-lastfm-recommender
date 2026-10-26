# Home Assistant App: Last.fm Music Recommender & Forgotten Favorites

**Language requirement:** All application UI text, messages, user documentation and Home Assistant script labels must be in English. Existing entity IDs and original music metadata must not be translated.

**Spotify cooldown (0.3.1):** HTTP 429 stops the request immediately and persists Spotify's Retry-After deadline. Scheduled/manual enrichment and restarts respect it without repeated Spotify requests or warnings; Last.fm enrichment continues. Album library displays the resume time. This prevents early retries but cannot clear Spotify's server-side limit or recover an independently stuck SpotifyPlus service call.

**Appearance (0.3.0):** Music Settings offers Light (the existing palette), Dark and Colorful. Theme selection stays in browser local storage, loads before styles and works for the current page if storage is blocked. All panels, controls and feedback use shared palette variables; browser verification covers contrast, mobile layout and persistence.

**UI and reliability update (0.2.3):** Refresh Music with a light blue/coral palette; handle Last.fm's empty tag/image fields and identify background errors. Add numeric volume and fine adjustment buttons with configurable display min/max, decimals and step. Read the current SpotifyPlus volume before step changes, keep values in HA's 0–1 range and disable volume controls when no reading exists. Sidebar playback on the target installation has been confirmed by the user; the new settings and error recovery have offline/browser coverage.

**Catalogue matching and album years (0.2.2):** Optional Spotify Client Credentials power a separate URI lookup queue with an explicit market (default FI). Unique exact artist/album matches from a complete search are linked automatically; ambiguous editions require explicit selection and confirmation. Existing confirmed links survive all background work. Four-digit Last.fm year tags move into album metadata and appear beside album names; conflicting years remain unknown. Offline matching, schema migration and browser flows are tested; live Spotify API access still needs verification on the target installation.

**Current UI direction (0.2.1):** Use the app's own Music page through HA Ingress. HA handles login; users enable Show in sidebar and select their SpotifyPlus player in Music Settings. No dashboard package, custom card or separately created HA token is required. Playback uses the Supervisor Core API proxy. Direct REST access remains optional and token-protected. The version 0.2.0 manual dashboard files are superseded by this approach; the genre/context model stays the same. Target-server Ingress and Core playback verification is still required.

## 1. Yleiskatsaus & Tavoite
Tämän Home Assistant Appin (uusi 2026.2+ -standardi, aiemmin Add-on) tavoitteena on analysoida 20 vuoden Last.fm-kuunteluhistoriaa (n. 300 000 scrobblea) ja tarjota Home Assistantin kautta älykkäitä musiikkisuosituksia ("unohtuneet helmet" ja kontekstihaut) suoraan HEOS-vahvistimelle Spotifyn kautta.

Sovellus pohjautuu viralliseen `home-assistant/apps-example`-templateen ja pyörii kokonaan kotipalvelimella (Proxmox / Home Assistant OS) Docker-konttina.

**Ensimmäinen tehtävä on testata Spotify–HEOS-toisto nykyisessä laiteympäristössä. Muu toteutus aloitetaan vasta, kun toimiva toistopolku ja sen rajoitteet on dokumentoitu.** Ensiversio sisältää historian, tavalliset suodattimet ja toiston. LLM- ja äänihaku lisätään myöhemmin.

---

## 2. Arkkitehtuuri & Repositoriorakenne
Projektin repositorio noudattaa HA:n virallista sovellusrakennetta, mikä mahdollistaa repositorion lisäämisen suoraan HA:n sovelluskauppaan (*App Store*):

```text
my-ha-apps/
├── repository.yaml             # Määrittelee HA App Storen tiedot
├── README.md                   # Repositorion ohjeet + My Home Assistant -asennusnappi
└── lastfm_recommender/         # Sovelluksen päähakemisto
    ├── config.yaml             # HA App -asetukset (API-avaimet jne.)
    ├── Dockerfile              # Python + lastfm-export -ympäristö
    ├── DOCS.md                 # Asennus- ja käyttöohjeet suoraan HA UI:ssa
    ├── run.py                  # Taustaprosessi (scrobblien lataus & rikastus)
    └── database.py             # SQLite-tietokantafunktiot & Text-to-SQL-logiikka
```

---

## 3. Tietokantamalli (`scrobbles.db` / SQLite)

Sovellus tallentaa datan SQLite-tietokantaan `/data/scrobbles.db` sovelluksen omaan pysyvään tallennustilaan. Kuunteluhistoriaa ei sijoiteta Home Assistantin staattisesti jaettavaan `/config/www`-hakemistoon. Tietokannan koko ja kyselyajat mitataan oikealla historialla; 25–35 MB ei ole luvattu koko.

Alla oleva skeema on luonnos. Ennen toteutusta määritellään skeemaversiot ja migraatiot, varmuuskopiointi SQLite backup API:lla tai vastaavalla johdonmukaisella menetelmällä sekä palautuskoe.

### Taulu: `scrobbles` (Yksittäiset kuuntelut)
```sql
CREATE TABLE scrobbles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,  -- UTC Unix -aikaleima
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL, -- 1=Ma, 7=Su
    hour INTEGER NOT NULL,        -- 0-23
    artist TEXT NOT NULL,
    album TEXT,                  -- Lähteestä puuttuva albumi säilyy puuttuvana
    track TEXT NOT NULL
);
```

### Taulu: `albums` (Rikastetut albumitiedot & kansikuvat)
```sql
CREATE TABLE albums (
    artist TEXT NOT NULL,
    album TEXT NOT NULL,
    spotify_uri TEXT,
    image_url TEXT,
    tags TEXT,                    -- Pilkulla erotetut genret/tagit
    scrobbles_total INTEGER DEFAULT 0,
    last_listened_at INTEGER,    -- Tarkka UTC Unix -aikaleima
    PRIMARY KEY (artist, album)
);
```

---

## 4. Rajapinnat & Integroitavuus

### Sovelluksen ja Home Assistantin työnjako
- Sovellus omistaa historian tuonnin, rikastuksen, tietokannan ja suosituslogiikan. Logiikka erotetaan moduuleihin, esimerkiksi `ingest.py`, `enrichment.py`, `recommendations.py` ja `api.py`.
- Pieni HTTP-rajapinta tarjoaa terveystiedon, synkronoinnin tilan ja suositushaun. Suositus sisältää albumin, artistin, perustelun, kansikuvan sekä vahvistetun Spotify-URI:n tai tiedon puuttuvasta vastaavuudesta.
- Home Assistant omistaa käyttöliittymän, automaatiot ja testatun toistoketjun. PyScript ei ole pakollinen riippuvuus; ensisijaisesti käytetään HA:n REST-toimintoja ja skriptejä.
- Rajapinnan autentikointi ja verkkoyhteys määritellään toteutuksessa. API-avaimia ja tokeneita ei lokiteta tai palauteta vastauksissa.

### API-avaimet
- **Last.fm API Key:** Hakujen, tagien ja historiatiedon rikastamiseen.
- **Spotify Developer App (Client ID & Client Secret):**
  - Web API: albumien tunnistus, `spotify_uri` ja saatavilla oleva kansikuva-URL. Tiettyä kuvakokoa tai URL:n pysyvyyttä ei oleteta.
  - Toistossa hyödynnetään ensisijaisesti HA:n Spotify-integraation tunnistautumista. Oma playback-OAuth ja refresh tokenien hallinta toteutetaan vain, jos playback-kokeilu osoittaa sen tarpeelliseksi.
  - Development Mode edellyttää Premium-tiliä. Tarkistetaan oman sovelluksen käytettävissä olevat endpointit ja kiintiöt toteutushetkellä. Toteutetaan välimuisti sekä `429`-vastausten ja mahdollisen `Retry-After`-arvon käsittely; kehittäjätilin sovellukset jakavat kiintiön.
- **Fallback Cover Art (Valinnainen):** Cover Art Archive (MusicBrainz MBID) tai iTunes Search API.

### Valinnainen LLM-rajapinta (myöhempi vaihe)
Käyttäjä voi halutessaan kytkeä LLM API -avaimen (esim. Gemini Flash / GPT-6 Luna) tai lokaalin Ollaman (Proxmox-palvelimelta).

- **Ensisijainen toimintaperiaate:** teksti → validoidut rakenteiset hakuehdot → sovelluksen parametrisoitu SQL. Mallille annetaan sallitut suodattimet ja tarvittava aikakonteksti, ei koko kuunteluhistoriaa.
- Jos myöhemmin tarvitaan vapaata Text-to-SQL:ää, käytetään vain luku -yhteyttä, sallittujen taulujen ja operaatioiden rajausta, tulosrajaa ja suoritusaikarajaa. Pelkkä kehotteen ohje käyttää `SELECT`-lausetta ei riitä.
- **Esimerkki:** viikonloppuaamu voidaan tulkita ehdoiksi `day_of_week IN (6,7) AND hour BETWEEN 6 AND 10`. Jos tarkoitetaan päivän ensimmäistä kuuntelua, tarvitaan lisäksi päivän ensimmäisen tapahtuman tunnistus. Pelkkä tuntirajaus ei vastaa tähän kysymykseen.
- Epäselvä aikailmaus täsmennetään tai tulkinta näytetään käyttäjälle. Tokenkulutus, kustannus ja viive mitataan; aiemmat 500–1000 tokenin ja alle 2 ms:n luvut ovat arvioita.

---

## 5. Toteutusvaiheet

### Ensiversion toteutustilanne (0.1.0, 25.10.2026)

- Virallinen example-template korvattu `lastfm_recommender/`-sovelluksella; amd64/aarch64 ja paikallinen Supervisor-build ilman image-julkaisua.
- Toteutettu suora Last.fm API -tuonti, pysyvä SQLite, sivukohtaiset tarkistuspisteet, limittäiset lisäpäivitykset ja lähdetapahtumien monikertaisuuden säilytys.
- Toteutettu Last.fm-rikastus, valinnainen Spotify-hakuehdotus, käyttäjän vahvistamat albumi-URI:t, tagit ja suodatetut satunnaissuositukset. Spotify-osumia ei automaattisesti vahvisteta.
- Toteutettu paikallinen selainkäyttöliittymä ja Bearer-tokenilla suojattu HTTP-rajapinta portissa 8099, tilatiedot ja SQLite backup API -varmuuskopio. Ei ingressiä ensiversiossa.
- HA:n REST-komento ja SpotifyPlus-toistoskripti dokumentoitu `lastfm_recommender/DOCS.md`-tiedostossa. Toisto on erillään suosittelijasovelluksesta.
- Automaattiset offline-testit ja synteettisellä historialla ajettu selaintesti kattavat keskeisen toimintopolun. GitHub Actionsin konttibuild onnistui. Käyttäjä on vahvistanut HA OS -asennuksen, oikean historian tuonnin ja suositukset toimiviksi. HA:n REST-skriptin kokonaiskoe on vielä avoinna.
- Vielä avoinna: vahvistimen nimenomainen laitekohdistus toisen Spotify-laitteen ollessa aktiivinen, vanhojen lähdemuutosten sovitus ja laajempi albumivarianttien tunnistus. Lisäävä synkronointi ei poista lähteestä poistettuja tapahtumia.
- Versioon 0.2.0 toteutettu Music-dashboardin kortti, HA-paketti ja genre-API. Pilvi näyttää genret ennen suositushakua, oletuksena 12 aikaan sopivaa genreä. Viikonpäiväryhmät ovat ma–to, perjantai ja la–su; kellonaikaikkuna ±2 tuntia. All genres ja haku avaavat muita tageja. Valinta ei käynnistä hakua tai toistoa automaattisesti. Ehdotusta voi esikatsella ja toisto käynnistetään erikseen.
- Genrejen rikastus toimii kymmenen albumin erissä oletuksena viiden minuutin välein; historian päivitys pysyy kuudessa tunnissa. Olemassa oleva tietokanta säilyy päivityksessä.
- Myöhemmäksi jätetty: käyttäjän määrittelemät viikonpäivä-/kellonaikajaksot, perheen läsnäoloon kytketyt kontekstit, LLM, äänihaku ja erillinen HACS-integraatio. Version 0.2.0 dashboard-asennus ja HA-kokonaiskoe varmennetaan vielä oikeassa ympäristössä.

### Vaihe 0: Spotify–HEOS-playback ensin
**Testitulos 25.10.2026:** SpotifyPlus on asennettu HACSilla. Albumin käynnistäminen toimii testatulla HEOS-vahvistimella sekä aktiivisena että valmiustilasta. Testiympäristössä erillistä `turn_on`-kutsua ei tarvita eikä vahvistimen HA-entiteetti tue sitä. Tuki on laitekohtainen.

Toimiva vähimmäiskutsu:

```yaml
action: spotifyplus.player_media_play_context
data:
  entity_id: media_player.your_spotifyplus_player
  context_uri: "spotify:album:0S2DmRfqWM51FUprHs0qil"
```

Testialbumi: Sufjan Stevens – Illinois. URI:n tunniste otetaan Spotify-linkin `/album/`-osan jälkeen; `?si=...` on jakoparametri eikä albumin tunniste. Myös kokonainen albumilinkki kelpaa `context_uri`-arvoksi.

Esimerkin `media_player.your_spotifyplus_player` korvataan oman SpotifyPlus-entiteetin tunnisteella. Pause-toiminto on myös testattu onnistuneesti. Toimiva albumikutsu jättää `device_id`-parametrin pois ja käyttää aktiivista Spotify-laitetta (tai SpotifyPlusin oletuslaitetta, jos aktiivista ei ole). Spotify Connect -nimellä kohdistamista ei ole vielä varmennettu oikealla albumi-URI:lla. Aiemman epäonnistumisen yhteydessä URI oli virheellinen, joten laitteen nimeä ei voi päätellä ongelman syyksi.

**Tilanne:** playbackin perusedellytys on todennettu ja muu toteutus voi alkaa. Ennen lopullista automaatiota varmennetaan vielä nimenomainen vahvistinkohdistus (myös toisen Spotify-laitteen ollessa aktiivinen), pitkän käyttötauon jälkeinen käynnistys ja palautuminen HA:n uudelleenkäynnistyksestä. Toistokerrokseksi valitaan ensisijaisesti SpotifyPlus; sovelluksen omaa playback-OAuthia ei tämän testin perusteella tarvita.

Alkuperäinen testilista ja täydentävät kokeet:

Kokeilu tehdään nykyisessä Home Assistantissa ilman omaa sovellusta tai historian tuontia.

1. Selvitetään Spotify- ja HEOS-entiteetit, Premium-tili ja vahvistimen näkyminen Spotify Connect -laitteena.
2. Valitaan yksi tunnettu, tilillä saatavilla oleva Spotify-albumi ja kirjataan sen URI.
3. Kokeillaan HA:n Spotify-integraatiota: vahvistin valitaan Spotify-entiteetin lähteeksi (`media_player.select_source`) ja albumi käynnistetään Spotify-entiteetillä (`media_player.play_media`). Tarkat parametrit varmennetaan käytössä olevalla integraatiolla.
4. Testataan vahvistimen ollessa käytössä, joutilaana ja valmiustilassa sekä laitteen puuttuessa Spotifyn lähdelistasta. Spotify API ei voi aloittaa toistoa laitteessa, jota se ei tunne.
5. Testataan albumin vaihto, tauko, jatkaminen ja äänenvoimakkuuden säätö tarkoitukseen sopivilla entiteeteillä.
6. Tallennetaan toimiva HA-skripti tai toimintoketju, entiteetit, herätys-/lähteenvalintavaiheet sekä virhetilanteiden palautumisohjeet.

**Hyväksymiskriteeri:** tunnettu albumi kuuluu oikeasta vahvistimesta HA-toiminnolla ja käynnistymisen edellytykset tunnetaan. Spotify-URI:n lähettämistä suoraan HEOS-entiteetille ei oleteta toimivaksi. Jos toisto ei onnistu, vaihtoehto ratkaistaan ennen seuraavia vaiheita. Mahdollinen manuaalinen Connect-aktivointi tai valmiustilarajoite hyväksytään tietoisesti ja dokumentoidaan.

### Vaihe 1: HA App -rakenne & Docker Setup
- Luodaan `repository.yaml` ja sovelluksen hakemistorakenne virallisen templaten mukaisesti.
- `config.yaml`: Määritellään valinnaiset kentät API-avaimille (Last.fm, Spotify, LLM/Ollama).
- `Dockerfile`: Valitaan kohdearkkitehtuurille sopiva Python-pohjakuva ja kiinnitetään riippuvuuksien versiot. SQLiteen käytetään Pythonin `sqlite3`-moduulia. `pandas`, `uv` ja erillinen SQLite-työkalu lisätään vain tarpeeseen.
- Varmennetaan `/data`-säilytys, asetusten validointi, skeemamigraatiot ja datan säilyminen uudelleenkäynnistyksessä.

### Vaihe 2: Ingest, Rikastus & SQLite (`run.py` & `database.py`)
1. Arvioidaan `lastfm-export`-työkalun soveltuvuus sivutettuun tuontiin, keskeytyksestä jatkamiseen ja lisäpäivityksiin. Tarvittaessa käytetään Last.fm API:a suoraan. Last.fm-käyttäjänimi ja API-avain määritellään asetuksissa.
2. Tuodaan historia erissä transaktioilla ja tallennetaan tarkistuspisteet `sync_state`-tauluun. Tuonnin yläaikaraja voidaan kiinnittää, jotta uudet kuuntelut eivät siirrä käsiteltäviä sivuja kesken tuonnin.
3. Haetaan uudet kuuntelut säännöllisesti limittäiseltä aikaikkunalta. Uudelleenajo ei saa kasvattaa historiaa duplikaateilla. Pelkkä aikaleima–artisti–kappale-yksikäsitteisyys ei saa poistaa lähteen aitoja toistoja: sovitus huomioi tarvittaessa tapahtumien esiintymismäärät. Parhaillaan soivaa kappaletta ei tallenneta valmistuneena kuunteluna.
4. Säilytetään UTC-aikaleima ja johdetaan kalenterikentät asetetussa aikavyöhykkeessä, oletuksena `Europe/Helsinki`, kesäaika huomioiden. Aikavyöhykkeen vaihtuessa kentät lasketaan uudelleen.
5. Säilytetään alkuperäiset nimet ja mahdolliset MBID-tunnisteet. Normalisoidut hakumuodot tallennetaan erikseen. Puuttuvia albuminimiä ei yhdistetä yhdeksi albumiksi.
6. Albumeille lisätään sisäinen tunniste, vastaavuuden tila ja luotettavuus sekä rikastuksen päivitysaika. Deluxe-, remaster- ja samannimiset julkaisut huomioidaan. Epävarma Spotify-osuma vaatii vahvistuksen tai korjauksen ennen automaattista toistoa.
7. Haetaan Last.fm-tagit, Spotify-URI:t ja kansikuvat erissä. Tagit siirretään erilliseen `album_tags`-tauluun tarkkaa suodatusta varten. Myös puuttuvat osumat välimuistitetaan määräajaksi. Rikastuksen virhe ei estä historian päivitystä.
8. Toteutetaan aikakatkaisut, rajatut uudelleenyritykset ja kasvava viive. Luodaan albumi-, aikaleima- ja kontekstihakujen indeksit. Yhteenvetojen pitää olla uudelleenlaskettavissa historiasta.

**Varmennus:** keskeytyneen tuonnin jatkaminen, saman erän uudelleenajo, aitojen toistojen säilyminen, kesäaikarajat, puuttuvat albumit, lähteeseen verratut kuuntelumäärät otoksella sekä varmuuskopion palautus.

### Vaihe 3: Suosituslogiikka ja HTTP-rajapinta
- Toteutetaan suositukset sovelluksessa ja yhdistetään HTTP-rajapinta HA:n skripteihin.
- **Perustila (UI-suodattimet):** Parametrit `genre`, `min_years_unheard`, `min_total_scrobbles`.
- Unohtuneen suosikin raja lasketaan tarkasta viimeisestä kuunteluhetkestä määritellyllä kalenterivuosien laskentasäännöllä. Genre-suodatin on valinnainen, koska tagit voivat puuttua.
- Vastaus perustelee valinnan kuuntelumäärällä ja viimeisellä kuuntelulla. Määritellään tasatilanteiden järjestys ja mahdollinen satunnaisuus, jotta sama albumi ei toistu jatkuvasti.
- Tyhjä hakutulos ja puuttuva Spotify-vastaavuus käsitellään tavallisina tilanteina. Toisto käyttää vain vahvistettua URI:a ja vaiheen 0 todennettua toimintoketjua.

### Vaihe 4: Dashboard & UI
- Dashboard-kortti (Mushroom / Mini Media Player), jossa kansikuva näytetään suoraan `image_url`-osoitteesta.
- Ensiversiossa suodattimet, perustelu, synkronoinnin tila ja toiston ohjaus. Puuttuvalle kuvalle on oletuskuva ja puuttuvalle Spotify-laitteelle ymmärrettävä toimintaohje.
- Hyväksymiskoe: historian päivitys → suositus → oikea albumi oikealla vahvistimella.

### Vaihe 5: Valinnainen luonnollisen kielen ja äänen käyttöliittymä
- Lisätään validoitu rakenteinen hakutulkinta vasta peruspolun toimittua. Äänisyöte liitetään sen jälkeen HA:n käytössä olevaan ääniratkaisuun.
- LLM-virhe tai puuttuva avain ei estä suodattimien käyttöä.

## 6. Lähteet

Suunnitelman arvioinnissa tarkistetut lähteet (25.10.2026). Ominaisuudet varmennetaan vielä toteutushetkellä ja omalla laitteistolla.

- [Home Assistant: Spotify](https://www.home-assistant.io/integrations/spotify/)
- [Home Assistant: Denon HEOS](https://www.home-assistant.io/integrations/heos/)
- [Home Assistant: sovelluksen asetukset](https://github.com/home-assistant/developers.home-assistant/blob/master/docs/apps/configuration.md)
- [Spotify: Quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)
- [Spotify: Development Mode -kiintiöpäivitys](https://developer.spotify.com/blog/2026-07-23-web-api-quota-updates)
