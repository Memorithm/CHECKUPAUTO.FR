# 0.3.12 (15) — sécurité de la connexion et des données locales

Cette version intègre les correctifs de l'audit de sécurité d'octobre 2026.

- **Connexion Google (S-05)** : l'application envoie un défi PKCE (`code_challenge`, S256) et ne peut échanger le ticket mobile qu'avec le vérificateur qu'elle seule détient. Un ticket intercepté ne suffit plus à ouvrir une session.
- **Connexion Apple (S-06)** : l'application récupère un nonce à usage unique émis par le serveur (`POST /api/mobile/auth/apple/nonce`, valable 10 minutes). Si ce nonce est indisponible ou trop ancien, elle revient au nonce local, que le serveur accepte encore.
- **Immatriculations (I-02)** : les échéances locales, immatriculations comprises, quittent `UserDefaults` pour le trousseau iOS (classe `AfterFirstUnlock`, pour que les rappels puissent être replanifiés en arrière-plan). Les données existantes sont migrées au premier lancement ; la copie en clair n'est supprimée qu'après une écriture réussie.

Côté serveur, `CYBERCHECK_MOBILE_PKCE_REQUIRED` et `CYBERCHECK_APPLE_SERVER_NONCE_REQUIRED` restent désactivés. Ils ne seront activés qu'après la publication de cette version sur l'App Store et son adoption, pour ne pas bloquer les versions antérieures.
