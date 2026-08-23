# Impertio Agent

Eigen kopie van [frappe/agent](https://github.com/frappe/agent), het hulpprogramma dat
Press op elke beheerde server installeert en dat daar opdrachten uitvoert (benches
bouwen, sites aanmaken, back-ups draaien).

## Waarom een eigen kopie

Press installeert de agent rechtstreeks vanaf GitHub en bouwt dat adres als
`github.com/<eigenaar>/agent`; de eigenaar staat in onze Press Settings
(`agent_repository_owner`). Met deze kopie bepalen wij welke code onze servers
binnenhalen, en kan die niet onder ons vandaan veranderen. De repo-naam moet
daarom exact `agent` zijn.

## Branchmodel

| Branch | Betekenis |
|---|---|
| `develop` | ongewijzigde spiegel van frappe/agent |
| `impertio` | onze werktak; nu gelijk aan de spiegel plus deze README, zonder patches |

Er zijn bewust geen code-wijzigingen: alle Impertio-patches zitten in de
[press-kopie](https://github.com/Impertio-Studio/press). Komt hier ooit een patch,
dan volgt die dezelfde regels: een eigen commit met het waarom en een verwijzing
naar het interne patchplan (dossier Operatie Navelstreng).

## Bijwerken vanaf upstream

```
git fetch upstream
git checkout develop && git merge --ff-only upstream/develop
# daarna `impertio` bewust bijzetten; nieuwe upstream-stand is een beslissing
```

## Wat hier nooit in komt

Geen geheimen, adressen, tokens of configuratie van onze omgeving.
