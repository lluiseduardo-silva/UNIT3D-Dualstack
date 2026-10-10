use indexmap::IndexMap;
use parking_lot::Mutex;
use std::{
    net::{IpAddr, SocketAddr},
    str::FromStr,
    time::{Duration, Instant},
};
use tokio::{net::TcpStream, sync::Semaphore};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedNetwork {
    ip: IpAddr,
    prefix: u32,
}

impl FromStr for TrustedNetwork {
    type Err = &'static str;
    fn from_str(value: &str) -> Result<Self, Self::Err> {
        let (address, prefix) = value
            .split_once('/')
            .map_or((value, None), |(a, p)| (a, Some(p)));
        let ip: IpAddr = address.parse().map_err(|_| "Proxy invalido")?;
        let width = if ip.is_ipv4() { 32 } else { 128 };
        let prefix = prefix
            .map(str::parse::<u32>)
            .transpose()
            .map_err(|_| "Prefixo invalido")?
            .unwrap_or(width);
        if prefix > width {
            return Err("Prefixo invalido");
        }
        Ok(Self { ip, prefix })
    }
}

impl TrustedNetwork {
    pub fn contains(&self, ip: IpAddr) -> bool {
        match (self.ip, ip) {
            (IpAddr::V4(net), IpAddr::V4(ip)) => {
                self.prefix == 0
                    || u32::from(net) >> (32 - self.prefix) == u32::from(ip) >> (32 - self.prefix)
            }
            (IpAddr::V6(net), IpAddr::V6(ip)) => {
                self.prefix == 0
                    || u128::from(net) >> (128 - self.prefix)
                        == u128::from(ip) >> (128 - self.prefix)
            }
            (IpAddr::V4(_), IpAddr::V6(ip)) => ip
                .to_ipv4_mapped()
                .is_some_and(|ip| self.contains(IpAddr::V4(ip))),
            _ => false,
        }
    }
}

/// Cache limitado e no maximo 128 conexoes em voo, sem espera na fila de probes.
pub struct ProbeCache {
    cache: Mutex<IndexMap<SocketAddr, (Instant, bool)>>,
    slots: Semaphore,
}

impl Default for ProbeCache {
    fn default() -> Self {
        Self {
            cache: Mutex::new(IndexMap::new()),
            slots: Semaphore::new(128),
        }
    }
}

impl ProbeCache {
    pub async fn check(&self, address: SocketAddr, capacity: usize, ttl: Duration) -> Option<bool> {
        let cached = {
            let mut cache = self.cache.lock();
            while cache.len() > capacity {
                cache.swap_remove_index(0);
            }
            cache.get(&address).copied()
        };
        if let Some((expires, value)) = cached {
            if expires > Instant::now() {
                return Some(value);
            }
        }
        let _permit = self.slots.try_acquire().ok()?;
        let result = tokio::time::timeout(Duration::from_millis(500), TcpStream::connect(address))
            .await
            .is_ok_and(|connection| connection.is_ok());
        let mut cache = self.cache.lock();
        cache.swap_remove(&address);
        while capacity > 0 && cache.len() >= capacity {
            cache.swap_remove_index(0);
        }
        if capacity > 0 {
            cache.insert(address, (Instant::now() + ttl, result));
        }
        Some(result)
    }

    pub fn expire(&self) {
        self.cache
            .lock()
            .retain(|_, (expires, _)| *expires > Instant::now());
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn proxies_explicit_and_family_scoped() {
        let v4: TrustedNetwork = "172.29.92.0/24".parse().unwrap();
        assert!(v4.contains("172.29.92.10".parse().unwrap()));
        assert!(v4.contains("::ffff:172.29.92.10".parse().unwrap()));
        assert!(!v4.contains("172.29.93.10".parse().unwrap()));
        let v6: TrustedNetwork = "fd42:756e:6974:92::/64".parse().unwrap();
        assert!(v6.contains("fd42:756e:6974:92::10".parse().unwrap()));
        assert!(!v6.contains("fd42:756e:6974:93::10".parse().unwrap()));
        for bad in ["*", "172.29.92.10/33", "::1/129", "::1/-1", ""] {
            assert!(bad.parse::<TrustedNetwork>().is_err());
        }
    }

    #[tokio::test]
    async fn connectivity_cache_is_bounded_and_expires() {
        let cache = ProbeCache::default();
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        assert_eq!(
            cache.check(address, 2, Duration::from_millis(1)).await,
            Some(true)
        );
        drop(listener);
        tokio::time::sleep(Duration::from_millis(5)).await;
        assert_eq!(
            cache.check(address, 2, Duration::from_secs(60)).await,
            Some(false)
        );
        for port in 1..=6 {
            cache
                .check(
                    SocketAddr::from(([127, 0, 0, 1], port)),
                    2,
                    Duration::from_secs(60),
                )
                .await;
            assert!(cache.cache.lock().len() <= 2);
        }
        cache.check(address, 1, Duration::from_secs(60)).await;
        assert_eq!(cache.cache.lock().len(), 1);
        // Ocupacao nao abre uma fila auxiliar sem limite.
        let _all = cache.slots.acquire_many(128).await.unwrap();
        assert_eq!(
            cache
                .check(
                    SocketAddr::from(([127, 0, 0, 1], 65534)),
                    1,
                    Duration::from_secs(60)
                )
                .await,
            None
        );
    }
}
