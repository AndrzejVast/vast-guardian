# Vast Guardian

Profesjonalny system monitorowania i zarządzania hostami Vast.ai.

## Plan projektu

- Monitorowanie hostów
- Automatyczne wykrywanie awarii
- Panel WWW
- Zarządzanie wieloma hostami
- Kopie zapasowe
- Aktualizacje jednym poleceniem

Projekt tworzony przez AndrzejVast przy wsparciu ChatGPT.

## Instalacja

Na wspieranym Ubuntu 22.04 lub 24.04 sklonuj repozytorium i uruchom lokalny
instalator. Instalator nie używa `curl | bash`, nie instaluje pakietów i przed
każdą zmianą pokazuje plan.

```bash
git clone https://github.com/AndrzejVast/vast-guardian.git
cd vast-guardian
sudo ./install.sh --role central
```

Tryb `central` tworzy lokalną bazę SQLite (lub bezpiecznie migruje istniejącą
z backupem), przygotowuje `/etc/vast-guardian/guardian.env` z prawami `0600`
i instaluje wyłącznie usługi Vast Guardian. Istniejący plik env nie jest
nadpisywany.

```bash
sudo ./install.sh --role agent \
  --central-url https://guardian.example.net/api/v1/ingest \
  --ingest-token 'replace-with-secret'
```

Tryb `agent` zapisuje wyłącznie konfigurację poza repozytorium. Transport
agent → centrala nie jest jeszcze zaimplementowany, dlatego instalator celowo
nie uruchamia usługi collectora, dashboardu ani Telegrama w tej roli.

Przed instalacją można sprawdzić plan bez zmian:

```bash
sudo ./install.sh --role central --dry-run
```

Instalator celowo nie zmienia sterowników NVIDIA, Docker/Vast.ai, sieci,
systemu operacyjnego ani workloadów klientów.
